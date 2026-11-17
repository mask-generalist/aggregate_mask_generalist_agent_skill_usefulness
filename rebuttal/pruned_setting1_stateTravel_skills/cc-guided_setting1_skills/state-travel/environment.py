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

    def cancel_booking(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cancel a booking if eligible per policy.

        TWO-STEP PROCESS (advisory):
        1. First call: without confirm=true — returns a preview of cancellation terms.
        2. Second call: with confirm=true — executes the cancellation.

        If the agent skips the preview and calls with confirm=true directly, the cancellation still executes.
        """
        booking_id = params.get("booking_id", "")
        booking = self.bookings.get(booking_id)
        if not booking:
            return {"error": f"Booking {booking_id} not found."}
        if booking.status == "cancelled":
            return {"error": f"Booking {booking_id} is already cancelled."}

        # Check if the airline cancelled the flight or delay >= 240 min (free cancellation)
        flight = self.flights.get(booking.flight_id)
        airline_cancelled = flight is not None and flight.status == "cancelled"
        severe_delay = flight is not None and flight.status == "delayed" and flight.delay_minutes >= 240

        policy = policies.check_cancellation_policy(
            cabin_class=booking.cabin_class,
            booked_at=booking.booked_at,
            now=self.now,
            has_insurance=booking.add_insurance or False,
            airline_cancelled=airline_cancelled or severe_delay,
            price_paid=booking.price_paid,
            route_type=flight.route_type if flight else "domestic",
        )

        if not policy["eligible"]:
            return {"status": "rejected", "reason": policy["reason"]}

        confirm = self.parse_bool(params.get("confirm"))
        if not confirm:
            # Return preview — do NOT actually cancel
            refund = booking.price_paid - policy["fee"]
            self._cancel_previewed.add(booking_id)
            return {
                "status": "preview",
                "booking_id": booking_id,
                "cancellation_fee": policy["fee"],
                "refund_amount": refund,
                "reason": policy["reason"],
            }

        # Two-step is advisory: execute even if preview was skipped
        booking.status = "cancelled"
        booking.cancellation_fee = policy["fee"]
        refund = booking.price_paid - policy["fee"]

        # Refund loyalty points if booking was paid entirely with points. Keep cash refund at $0.
        if booking.payment_method == "points" and booking.points_used and booking.points_used > 0:
            refund = 0
            booking.points_refunded = booking.points_used

        booking.refund_amount = refund
        refund = booking.refund_amount

        # Refund loyalty points if booking was paid with points
        if booking.payment_method == "points" and booking.points_used and booking.points_used > 0:
            user = self.users.get(booking.user_id)
            if user:
                user.loyalty_points += booking.points_used

        return {
            "status": "cancelled",
            "booking_id": booking_id,
            "refund_amount": refund,
            "cancellation_fee": policy["fee"],
            "reason": policy["reason"],
        }

    # -------------------------------------------------------------------
    # Hotel tools
    # -------------------------------------------------------------------

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

    def cancel_hotel_reservation(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cancel a hotel reservation. Two-step: preview then confirm (advisory — skipping preview still executes)."""
        reservation_id = params.get("reservation_id", "")
        hotel = self.hotels.get(reservation_id)
        if not hotel:
            return {"error": f"Hotel reservation {reservation_id} not found."}
        if hotel.status == "cancelled":
            return {"error": f"Hotel reservation {reservation_id} is already cancelled."}

        policy = policies.check_hotel_cancellation_policy(
            room_type=hotel.room_type,
            check_in=hotel.check_in,
            now=self.now,
            nightly_rate=hotel.nightly_rate,
            total_price=hotel.total_price,
        )

        confirm = self.parse_bool(params.get("confirm"))
        if not confirm:
            self._hotel_cancel_previewed.add(reservation_id)
            return {
                "status": "preview",
                "reservation_id": reservation_id,
                "cancellation_fee": policy["fee"],
                "refund_amount": policy["refund"],
                "reason": policy["reason"],
            }

        hotel.status = "cancelled"
        hotel.cancellation_fee = policy["fee"]
        hotel.refund_amount = policy["refund"]

        return {
            "status": "cancelled",
            "reservation_id": reservation_id,
            "cancellation_fee": policy["fee"],
            "refund_amount": policy["refund"],
            "reason": policy["reason"],
        }

    # -------------------------------------------------------------------
    # Car rental tools
    # -------------------------------------------------------------------

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

    def book_car_rental(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a car rental reservation from searchable car inventory."""
        car_id = params.get("car_id", "")
        car = self.car_inventory.get(car_id)
        if not car:
            return {"error": f"Car rental option {car_id} not found."}

        user_id = params.get("user_id", "")
        if user_id not in self.users:
            return {"error": f"User {user_id} not found."}

        existing_nums = []
        for rid in self.car_rentals:
            if rid.startswith("CR-"):
                try:
                    existing_nums.append(int(rid.split("-")[1]))
                except ValueError:
                    pass
        next_num = max(existing_nums, default=0) + 1
        rental_id = f"CR-{next_num:04d}"

        rental = CarRental(
            rental_id=rental_id,
            user_id=user_id,
            car_id=car.car_id,
            company=car.company,
            pickup_location=car.pickup_location,
            dropoff_location=car.dropoff_location,
            pickup_date=car.pickup_date,
            dropoff_date=car.dropoff_date,
            car_class=car.car_class,
            daily_rate=car.daily_rate,
            total_price=car.total_price,
            status="confirmed",
            insurance_included=car.insurance_included,
            booked_at=self.now,
        )
        self.car_rentals[rental_id] = rental

        return {
            "status": "confirmed",
            "rental_id": rental_id,
            "car_id": car.car_id,
            "company": car.company,
            "car_class": car.car_class,
            "total_price": car.total_price,
        }

    def get_car_rental(self, params: dict[str, Any]) -> dict[str, Any]:
        """Look up a car rental by ID."""
        rental_id = params.get("rental_id", "")
        car = self.car_rentals.get(rental_id)
        if not car:
            return {"error": f"Car rental {rental_id} not found."}
        return car.to_dict()

    def cancel_car_rental(self, params: dict[str, Any]) -> dict[str, Any]:
        """Cancel a car rental. Two-step: preview then confirm (advisory — skipping preview still executes)."""
        rental_id = params.get("rental_id", "")
        car = self.car_rentals.get(rental_id)
        if not car:
            return {"error": f"Car rental {rental_id} not found."}
        if car.status == "cancelled":
            return {"error": f"Car rental {rental_id} is already cancelled."}

        policy = policies.check_car_rental_cancellation_policy(
            car_class=car.car_class,
            pickup_date=car.pickup_date,
            now=self.now,
            daily_rate=car.daily_rate,
            total_price=car.total_price,
        )

        confirm = self.parse_bool(params.get("confirm"))
        if not confirm:
            self._car_cancel_previewed.add(rental_id)
            return {
                "status": "preview",
                "rental_id": rental_id,
                "cancellation_fee": policy["fee"],
                "refund_amount": policy["refund"],
                "reason": policy["reason"],
            }

        car.status = "cancelled"
        car.cancellation_fee = policy["fee"]
        car.refund_amount = policy["refund"]

        return {
            "status": "cancelled",
            "rental_id": rental_id,
            "cancellation_fee": policy["fee"],
            "refund_amount": policy["refund"],
            "reason": policy["reason"],
        }

    # -------------------------------------------------------------------
    # Tool handler registry
    # -------------------------------------------------------------------

    @property
    def tool_handlers(self) -> dict[str, Any]:
        return {
            "get_user_reservations": self.get_user_reservations,
            "get_booking": self.get_booking,
            "get_policies": self.get_policies,
            "cancel_booking": self.cancel_booking,
            "book_hotel": self.book_hotel,
            "get_hotel_reservation": self.get_hotel_reservation,
            "cancel_hotel_reservation": self.cancel_hotel_reservation,
            "search_car_rentals": self.search_car_rentals,
            "book_car_rental": self.book_car_rental,
            "get_car_rental": self.get_car_rental,
            "cancel_car_rental": self.cancel_car_rental,
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
