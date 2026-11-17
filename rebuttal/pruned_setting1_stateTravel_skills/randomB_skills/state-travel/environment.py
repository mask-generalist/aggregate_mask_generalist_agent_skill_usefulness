"""Stateful travel environment with tool handlers.

The TravelEnvironment holds the in-memory database and provides tool handler
methods as bound functions. Each evaluation run gets a fresh deep copy.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import policies
from constants import REQUIRED_BOOKING_PREFERENCE_FIELDS
from policy_texts import get_policy_text
from schemas import (
    Booking,
    CarInventoryItem,
    CarRental,
    EnvironmentData,
    Flight,
    HotelInventoryItem,
    HotelReservation,
    User,
)
from core import BaseEnvironment

# City name → airport code mapping for hotel/car searches.
# Allows agents to search by city name (e.g., "Toronto") instead of airport code ("YYZ").
_CITY_ALIASES: dict[str, str] = {
    "toronto": "YYZ",
    "paris": "CDG",
    "london": "LHR",
    "miami": "MIA",
    "san francisco": "SFO",
    "los angeles": "LAX",
    "denver": "DEN",
    "chicago": "ORD",
    "new york": "JFK",
    "atlanta": "ATL",
    "dallas": "DFW",
    "seattle": "SEA",
    "boston": "BOS",
}


def _normalize_city(city: str) -> str:
    """Normalize a city name or airport code to uppercase airport code."""
    return _CITY_ALIASES.get(city.lower().strip(), city).upper()


def _available_cabins(flight: Flight) -> str:
    return ", ".join(sorted(flight.cabin_prices.keys())) if flight.cabin_prices else "none"


class TravelEnvironment(BaseEnvironment):
    """Stateful environment wrapping flights, bookings, users, hotels, car rentals and policy engine."""

    def __init__(self, env_data: EnvironmentData, now: str):
        super().__init__(env_data, now)
        # Index everything for fast lookup
        self.flights: dict[str, Flight] = {f.flight_id: f for f in env_data.flights}
        self.bookings: dict[str, Booking] = {b.booking_id: b for b in env_data.bookings}
        self.users: dict[str, User] = {u.user_id: u for u in env_data.users}
        self.hotel_inventory: dict[str, HotelInventoryItem] = {h.hotel_id: h for h in env_data.hotel_inventory}
        self.hotels: dict[str, HotelReservation] = {h.reservation_id: h for h in env_data.hotels}
        self.car_inventory: dict[str, CarInventoryItem] = {c.car_id: c for c in env_data.car_inventory}
        self.car_rentals: dict[str, CarRental] = {c.rental_id: c for c in env_data.car_rentals}
        # Track which bookings have had a cancellation preview (advisory — two-step still works but not enforced)
        self._cancel_previewed: set[str] = set()
        self._hotel_cancel_previewed: set[str] = set()
        self._car_cancel_previewed: set[str] = set()

    def get_full_snapshot(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Return a full snapshot of all entities for assertion checking."""
        return {
            "bookings": {bid: b.to_dict() for bid, b in self.bookings.items()},
            "users": {uid: u.to_dict() for uid, u in self.users.items()},
            "hotel_inventory": {hid: h.to_dict() for hid, h in self.hotel_inventory.items()},
            "hotels": {rid: h.to_dict() for rid, h in self.hotels.items()},
            "car_inventory": {cid: c.to_dict() for cid, c in self.car_inventory.items()},
            "car_rentals": {rid: c.to_dict() for rid, c in self.car_rentals.items()},
        }

    # -------------------------------------------------------------------
    # READ tools
    # -------------------------------------------------------------------

    def search_flights(self, params: dict[str, Any]) -> dict[str, Any]:
        """Search available flights matching criteria. Returns multiple results."""
        origin = params.get("origin", "")
        destination = params.get("destination", "")
        date = params.get("date", "")
        airline = params.get("airline")
        max_stops = params.get("max_stops")
        max_price = params.get("max_price")
        time_range = params.get("time_range")

        results = []
        for f in self.flights.values():
            # Only show scheduled or delayed flights (not cancelled)
            if f.status == "cancelled":
                continue
            # Match criteria
            if origin and f.origin != origin.upper():
                continue
            if destination and f.destination != destination.upper():
                continue
            if date and not f.departure_time.startswith(date):
                continue
            if airline and f.airline_code != airline.upper():
                continue
            if max_stops is not None:
                try:
                    if f.stops > int(max_stops):
                        continue
                except (ValueError, TypeError):
                    pass
            if max_price is not None:
                try:
                    price_limit = int(max_price)
                    # Include flight if ANY cabin price is within the limit
                    if price_limit >= 0 and f.cabin_prices and min(f.cabin_prices.values()) > price_limit:
                        continue
                except (ValueError, TypeError):
                    pass
            if time_range:
                dep_hour = datetime.fromisoformat(f.departure_time).hour
                if not _matches_time_range(dep_hour, time_range):
                    continue

            # Filter out flights that depart before 'now'
            now_dt = datetime.fromisoformat(self.now)
            dep_dt = datetime.fromisoformat(f.departure_time)
            if dep_dt < now_dt:
                continue

            results.append(
                {
                    "flight_id": f.flight_id,
                    "airline_code": f.airline_code,
                    "origin": f.origin,
                    "destination": f.destination,
                    "departure_time": f.departure_time,
                    "arrival_time": f.arrival_time,
                    "duration_minutes": f.duration_minutes,
                    "stops": f.stops,
                    "cabin_prices": f.cabin_prices,
                    "status": f.status,
                    "route_type": f.route_type,
                }
            )

        # Sort by departure time
        results.sort(key=lambda x: x["departure_time"])

        if not results:
            return {"flights": [], "message": "No flights found matching your criteria."}
        return {"flights": results[:10]}  # cap at 10 results

    def get_user_details(self, params: dict[str, Any]) -> dict[str, Any]:
        """Look up a customer's account details."""
        user_id = params.get("user_id", "")
        user = self.users.get(user_id)
        if not user:
            return {"error": f"User {user_id} not found."}
        return {
            "user_id": user.user_id,
            "name": user.name,
            "email": user.email,
            "loyalty_tier": user.loyalty_tier,
            "loyalty_points": user.loyalty_points,
        }

    def get_user_reservations(self, params: dict[str, Any]) -> dict[str, Any]:
        """List all reservation IDs for a customer."""
        user_id = params.get("user_id", "")
        if user_id not in self.users:
            return {"error": f"User {user_id} not found."}

        booking_ids = [b.booking_id for b in self.bookings.values() if b.user_id == user_id]
        hotel_ids = [h.reservation_id for h in self.hotels.values() if h.user_id == user_id]
        car_rental_ids = [c.rental_id for c in self.car_rentals.values() if c.user_id == user_id]

        return {
            "user_id": user_id,
            "booking_ids": booking_ids,
            "hotel_ids": hotel_ids,
            "car_rental_ids": car_rental_ids,
        }

    def get_booking(self, params: dict[str, Any]) -> dict[str, Any]:
        """Look up a booking by ID."""
        booking_id = params.get("booking_id", "")
        booking = self.bookings.get(booking_id)
        if not booking:
            return {"error": f"Booking {booking_id} not found."}

        result = booking.to_dict()
        # Include flight route info so agent can search for alternatives
        flight = self.flights.get(booking.flight_id)
        if flight:
            result["origin"] = flight.origin
            result["destination"] = flight.destination
            result["departure_time"] = flight.departure_time
            result["route_type"] = flight.route_type
        return result

    def get_policies(self, params: dict[str, Any]) -> dict[str, Any]:
        """Look up airline policies for cancel/change/baggage/delay/loyalty/upgrade."""
        return get_policy_text(params)

    # -------------------------------------------------------------------
    # WRITE tools
    # -------------------------------------------------------------------

    def _missing_booking_preference_field(self, params: dict[str, Any]) -> str | None:
        for field in REQUIRED_BOOKING_PREFERENCE_FIELDS:
            if field not in params:
                return field
        return None

    def _missing_booking_preference_error(self, params: dict[str, Any]) -> dict[str, str] | None:
        missing_pref = self._missing_booking_preference_field(params)
        if missing_pref is None:
            return None
        return {"error": f"missing required field: {missing_pref}"}

    @staticmethod
    def _cabin_unavailable_error(cabin_class: str, flight_id: str, flight: Flight) -> dict[str, str]:
        return {
            "error": f"Cabin class '{cabin_class}' not available on flight {flight_id}. Available: {_available_cabins(flight)}."
        }

    def create_booking(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new booking with explicit persisted booking preferences.

        Required persisted booking fields: meal_preference, cabin_class, seat_type,
        add_wifi, add_extra_legroom, and add_insurance. Runtime never infers these
        from the user profile.
        """
        flight_id = params.get("flight_id", "")
        flight = self.flights.get(flight_id)
        if not flight:
            return {"error": f"Flight {flight_id} not found."}
        if flight.status == "cancelled":
            return {"error": f"Flight {flight_id} is cancelled and cannot be booked."}

        user_id = params.get("user_id", "unknown")
        user = self.users.get(user_id)

        # Require cabin_class
        cabin_class = params.get("cabin_class")
        if not cabin_class:
            return {"error": f"cabin_class is required. Available cabins for this flight: {_available_cabins(flight)}."}
        if cabin_class not in flight.cabin_prices:
            return self._cabin_unavailable_error(cabin_class, flight_id, flight)

        cabin_price = flight.cabin_prices[cabin_class]

        # Require seat_type
        seat_type = params.get("seat_type")
        if not seat_type:
            return {"error": "seat_type is required. Must be one of: window, middle, aisle."}
        if seat_type not in ("window", "middle", "aisle"):
            return {"error": f"Invalid seat_type '{seat_type}'. Must be one of: window, middle, aisle."}

        # Require payment_method
        payment_method = params.get("payment_method")
        if not payment_method:
            return {"error": "payment_method is required. Must be one of: credit_card, points, points_plus_cash."}
        if payment_method not in ("credit_card", "points", "points_plus_cash"):
            return {
                "error": f"Invalid payment_method '{payment_method}'. Must be one of: credit_card, points, points_plus_cash."
            }

        missing_pref_error = self._missing_booking_preference_error(params)
        if missing_pref_error is not None:
            return missing_pref_error

        meal_preference = params["meal_preference"]
        add_wifi = self.parse_bool(params["add_wifi"])
        add_extra_legroom = self.parse_bool(params["add_extra_legroom"])
        add_insurance = self.parse_bool(params["add_insurance"])

        # Payment method handling (already validated above)
        points_used = 0
        cash_amount = cabin_price

        if payment_method in ("points", "points_plus_cash"):
            if not user:
                return {"error": f"User {user_id} not found. Cannot process points payment."}

            redemption = policies.check_loyalty_point_redemption(
                loyalty_tier=user.loyalty_tier,
                loyalty_points=user.loyalty_points,
                flight_price=cabin_price,
                route_type=flight.route_type,
            )
            if not redemption["eligible"]:
                return {"error": f"Points redemption not eligible: {redemption['reason']}"}

            points_used = redemption["points_used"]
            cash_amount = int(redemption["remaining_cash_payment"])

            # Require points_used for any points payment
            provided_points = params.get("points_used")
            if provided_points is None:
                return {"error": "points_used is required for points payments."}
            try:
                provided_points = int(provided_points)
            except (ValueError, TypeError):
                return {"error": f"Invalid points_used: {provided_points}. Must be an integer."}
            if provided_points != points_used:
                return {"error": "Incorrect points_used value."}

            # Reject payment_method="points" if points don't fully cover the flight
            if payment_method == "points" and cash_amount > 0:
                return {"error": "Insufficient points for full payment."}

            # Require cash_amount for points_plus_cash
            if payment_method == "points_plus_cash":
                provided_cash = params.get("cash_amount")
                if provided_cash is None:
                    return {"error": "cash_amount is required for points_plus_cash payments."}
                try:
                    provided_cash = int(provided_cash)
                except (ValueError, TypeError):
                    return {"error": f"Invalid cash_amount: {provided_cash}. Must be an integer (USD)."}
                if provided_cash != cash_amount:
                    return {"error": "Incorrect cash_amount value."}

            user.loyalty_points -= points_used

        # Extra baggage handling
        num_extra_bags = params.get("paid_checked_bags", 0)
        baggage_fee = 0
        if num_extra_bags and isinstance(num_extra_bags, int) and num_extra_bags > 0:
            # Use domestic rate as default
            baggage_fee = num_extra_bags * 35

        # Generate booking ID (handle non-numeric suffixes like BK-PR01, BK-A06a)
        existing_nums = []
        for bid in self.bookings:
            if bid.startswith("BK-"):
                try:
                    existing_nums.append(int(bid.split("-")[1]))
                except ValueError:
                    pass
        next_num = max(existing_nums, default=0) + 1
        booking_id = f"BK-{next_num:04d}"

        booking = Booking(
            booking_id=booking_id,
            user_id=user_id,
            flight_id=flight_id,
            status="confirmed",
            seat_type=params.get("seat_type"),
            cabin_class=cabin_class,
            meal_preference=meal_preference,
            add_wifi=add_wifi,
            add_extra_legroom=add_extra_legroom,
            add_insurance=add_insurance,
            price_paid=cash_amount + baggage_fee,
            payment_method=payment_method,
            points_used=points_used,
            cash_amount=cash_amount,
            booked_at=self.now,
            paid_checked_bags=num_extra_bags if isinstance(num_extra_bags, int) else 0,
        )
        self.bookings[booking_id] = booking

        result: dict[str, Any] = {
            "status": "confirmed",
            "booking_id": booking_id,
            "flight_id": flight_id,
            "cabin_class": cabin_class,
            "price": cabin_price,
            "payment_method": payment_method,
        }
        if points_used > 0:
            result["points_used"] = points_used
            result["cash_charged"] = cash_amount
        if baggage_fee > 0:
            result["baggage_fee"] = baggage_fee
            result["extra_bags"] = num_extra_bags

        return result

    def search_hotels(self, params: dict[str, Any]) -> dict[str, Any]:
        """Search available hotels by city, dates, room type, and max price."""
        city = _normalize_city(params.get("city", "")) if params.get("city") else ""
        room_type = params.get("room_type")
        max_price = params.get("max_price")

        results = []
        check_in = params.get("check_in")
        check_out = params.get("check_out")

        for h in self.hotel_inventory.values():
            if city and h.city.upper() != city:
                continue
            if check_in and h.check_in != check_in:
                continue
            if check_out and h.check_out != check_out:
                continue
            if room_type and h.room_type != room_type:
                continue
            if max_price is not None:
                try:
                    price_limit = int(max_price)
                    if price_limit >= 0 and h.nightly_rate > price_limit:
                        continue
                except (ValueError, TypeError):
                    pass
            results.append(
                {
                    "hotel_id": h.hotel_id,
                    "hotel_name": h.hotel_name,
                    "city": h.city,
                    "check_in": h.check_in,
                    "check_out": h.check_out,
                    "room_type": h.room_type,
                    "nightly_rate": h.nightly_rate,
                    "total_price": h.total_price,
                }
            )

        if not results:
            return {"hotels": [], "message": "No hotels found matching your criteria."}
        return {"hotels": results[:10]}

    def book_hotel(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a hotel reservation from a searchable hotel inventory item."""
        hotel_id = params.get("hotel_id", "")
        hotel = self.hotel_inventory.get(hotel_id)
        if not hotel:
            return {"error": f"Hotel option {hotel_id} not found."}

        user_id = params.get("user_id", "")
        if user_id not in self.users:
            return {"error": f"User {user_id} not found."}

        existing_nums = []
        for rid in self.hotels:
            if rid.startswith("HR-"):
                try:
                    existing_nums.append(int(rid.split("-")[1]))
                except ValueError:
                    pass
        next_num = max(existing_nums, default=0) + 1
        reservation_id = f"HR-{next_num:04d}"

        reservation = HotelReservation(
            reservation_id=reservation_id,
            user_id=user_id,
            hotel_id=hotel.hotel_id,
            hotel_name=hotel.hotel_name,
            city=hotel.city,
            check_in=hotel.check_in,
            check_out=hotel.check_out,
            room_type=hotel.room_type,
            nightly_rate=hotel.nightly_rate,
            total_price=hotel.total_price,
            status="confirmed",
            booked_at=self.now,
        )
        self.hotels[reservation_id] = reservation

        return {
            "status": "confirmed",
            "reservation_id": reservation_id,
            "hotel_id": hotel.hotel_id,
            "hotel_name": hotel.hotel_name,
            "total_price": hotel.total_price,
            "room_type": hotel.room_type,
        }

    def get_hotel_reservation(self, params: dict[str, Any]) -> dict[str, Any]:
        """Look up a hotel reservation by ID."""
        reservation_id = params.get("reservation_id", "")
        hotel = self.hotels.get(reservation_id)
        if not hotel:
            return {"error": f"Hotel reservation {reservation_id} not found."}
        return hotel.to_dict()

    def search_car_rentals(self, params: dict[str, Any]) -> dict[str, Any]:
        """Search available car rentals by location, dates, class, and max daily rate."""
        pickup_location = _normalize_city(params.get("pickup_location", "")) if params.get("pickup_location") else ""
        car_class = params.get("car_class")
        max_daily_rate = params.get("max_daily_rate")

        results = []
        pickup_date = params.get("pickup_date")
        dropoff_date = params.get("dropoff_date")

        for c in self.car_inventory.values():
            if pickup_location and c.pickup_location.upper() != pickup_location:
                continue
            if pickup_date and c.pickup_date != pickup_date:
                continue
            if dropoff_date and c.dropoff_date != dropoff_date:
                continue
            if car_class and c.car_class != car_class:
                continue
            if max_daily_rate is not None:
                try:
                    rate_limit = int(max_daily_rate)
                    if rate_limit >= 0 and c.daily_rate > rate_limit:
                        continue
                except (ValueError, TypeError):
                    pass
            results.append(
                {
                    "car_id": c.car_id,
                    "company": c.company,
                    "pickup_location": c.pickup_location,
                    "dropoff_location": c.dropoff_location,
                    "pickup_date": c.pickup_date,
                    "dropoff_date": c.dropoff_date,
                    "car_class": c.car_class,
                    "daily_rate": c.daily_rate,
                    "total_price": c.total_price,
                    "insurance_included": c.insurance_included,
                }
            )

        if not results:
            return {"car_rentals": [], "message": "No car rentals found matching your criteria."}
        return {"car_rentals": results[:10]}

    def get_car_rental(self, params: dict[str, Any]) -> dict[str, Any]:
        """Look up a car rental by ID."""
        rental_id = params.get("rental_id", "")
        car = self.car_rentals.get(rental_id)
        if not car:
            return {"error": f"Car rental {rental_id} not found."}
        return car.to_dict()

    @property
    def tool_handlers(self) -> dict[str, Any]:
        return {
            "search_flights": self.search_flights,
            "get_user_details": self.get_user_details,
            "get_user_reservations": self.get_user_reservations,
            "get_booking": self.get_booking,
            "get_policies": self.get_policies,
            "create_booking": self.create_booking,
            "search_hotels": self.search_hotels,
            "book_hotel": self.book_hotel,
            "get_hotel_reservation": self.get_hotel_reservation,
            "search_car_rentals": self.search_car_rentals,
            "get_car_rental": self.get_car_rental,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIME_RANGES = {
    "early_morning": (5, 8),
    "morning": (8, 12),
    "afternoon": (12, 17),
    "evening": (17, 21),
    "red_eye": (21, 5),
}


def _matches_time_range(hour: int, time_range: str) -> bool:
    bounds = _TIME_RANGES.get(time_range)
    if not bounds:
        return True
    start, end = bounds
    if start < end:
        return start <= hour < end
    else:  # wraps around midnight
        return hour >= start or hour < end
