"""Tool schemas (OpenAI function calling format) for the travel environment.

17 tools: 10 READ, 7 WRITE.
"""

from typing import Any

# ---------------------------------------------------------------------------
# READ tools
# ---------------------------------------------------------------------------

GET_USER_DETAILS: dict[str, Any] = {
    "type": "function",
    "name": "get_user_details",
    "description": "Look up a customer's account details including name, email, loyalty tier, and points balance.",
    "parameters": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "Customer user ID (e.g. 'user_001')"},
        },
        "required": ["user_id"],
    },
}

GET_USER_RESERVATIONS: dict[str, Any] = {
    "type": "function",
    "name": "get_user_reservations",
    "description": (
        "List all reservation IDs for a customer's flight bookings, hotel reservations, and car rentals. "
        "Use get_booking, get_hotel_reservation, or get_car_rental to look up details by ID."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "Customer user ID (e.g. 'user_001')"},
        },
        "required": ["user_id"],
    },
}

GET_BOOKING: dict[str, Any] = {
    "type": "function",
    "name": "get_booking",
    "description": "Retrieve the details of an existing booking by its booking ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "booking_id": {"type": "string", "description": "The booking ID (e.g. 'BK-0001')"},
        },
        "required": ["booking_id"],
    },
}

GET_FLIGHT_STATUS: dict[str, Any] = {
    "type": "function",
    "name": "get_flight_status",
    "description": "Check the current status of a flight (scheduled, delayed, or cancelled).",
    "parameters": {
        "type": "object",
        "properties": {
            "flight_id": {"type": "string", "description": "The flight ID (e.g. 'DL401')"},
        },
        "required": ["flight_id"],
    },
}

# ---------------------------------------------------------------------------
# WRITE tools
# ---------------------------------------------------------------------------

UPDATE_BOOKING: dict[str, Any] = {
    "type": "function",
    "name": "update_booking",
    "description": (
        "Update an existing booking. Only pass the fields you want to change for same-flight edits. "
        "If you pass flight_id to change flights, you must also pass cabin_class, seat_type, meal_preference, add_wifi, add_extra_legroom, and add_insurance explicitly. "
        "For a flight change, call with confirm=false first to preview the exact change fee, fare difference, and new total without applying anything, then call again (omit confirm or pass confirm=true) to execute."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "booking_id": {"type": "string", "description": "The booking ID to update"},
            "flight_id": {"type": "string", "description": "New flight ID (to change to a different flight)"},
            "change_reason": {
                "type": "string",
                "enum": ["personal", "medical", "bereavement", "jury_duty", "military", "schedule_change", "weather"],
                "description": "Reason for flight change (affects fee calculation)",
            },
            "cabin_class": {
                "type": "string",
                "enum": ["economy", "business", "first"],
                "description": "Upgrade cabin class on the same flight (upgrade fees apply)",
            },
            "seat_type": {
                "type": "string",
                "enum": ["window", "middle", "aisle"],
                "description": "New seat type",
            },
            "meal_preference": {
                "type": "string",
                "enum": ["standard", "vegetarian", "vegan", "kosher", "halal", "gluten_free"],
                "description": "New meal preference",
            },
            "add_wifi": {"type": "boolean", "description": "Set WiFi (true/false)"},
            "add_extra_legroom": {"type": "boolean", "description": "Set extra legroom (true/false)"},
            "add_insurance": {"type": "boolean", "description": "Set insurance (true/false)"},
            "delay_compensation": {
                "type": "string",
                "enum": ["none", "meal_voucher", "full"],
                "description": "Delay compensation to apply: 'none' (<2h delay), 'meal_voucher' (2-4h, $25 voucher), 'full' (4h+, rebooking + meal + hotel)",
            },
            "paid_checked_bags": {
                "type": "integer",
                "description": "Number of extra checked bags beyond free allowance ($35 each)",
            },
            "confirm": {
                "type": "boolean",
                "description": (
                    "For a flight change: pass false to preview the change fee, fare difference, and new total "
                    "without applying anything. Omit it (or pass true) to execute the change."
                ),
            },
        },
        "required": ["booking_id"],
    },
}

CANCEL_BOOKING: dict[str, Any] = {
    "type": "function",
    "name": "cancel_booking",
    "description": (
        "Cancel an existing booking. First call without confirm to preview the cancellation terms, "
        "then call with confirm=true to execute."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "booking_id": {"type": "string", "description": "The booking ID to cancel"},
            "confirm": {
                "type": "boolean",
                "description": "Confirm the cancellation after reviewing the terms.",
            },
        },
        "required": ["booking_id"],
    },
}

# ---------------------------------------------------------------------------
# Hotel tools
# ---------------------------------------------------------------------------

SEARCH_HOTELS: dict[str, Any] = {
    "type": "function",
    "name": "search_hotels",
    "description": "Search for available hotels in a city. Filter by dates, room type, and price.",
    "parameters": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name or airport code area (e.g. 'LHR', 'CDG', 'MIA')"},
            "check_in": {"type": "string", "description": "Check-in date in YYYY-MM-DD format"},
            "check_out": {"type": "string", "description": "Check-out date in YYYY-MM-DD format"},
            "room_type": {
                "type": "string",
                "enum": ["standard", "suite"],
                "description": "Filter by room type",
            },
            "max_price": {
                "type": "integer",
                "description": "Maximum nightly rate in USD. Use -1 for no limit.",
            },
        },
        "required": ["city"],
    },
}

BOOK_HOTEL: dict[str, Any] = {
    "type": "function",
    "name": "book_hotel",
    "description": "Book a hotel option returned by search_hotels for a customer.",
    "parameters": {
        "type": "object",
        "properties": {
            "hotel_id": {"type": "string", "description": "Hotel option ID from search_hotels"},
            "user_id": {"type": "string", "description": "Customer user ID"},
        },
        "required": ["hotel_id", "user_id"],
    },
}

GET_HOTEL_RESERVATION: dict[str, Any] = {
    "type": "function",
    "name": "get_hotel_reservation",
    "description": "Retrieve the details of an existing hotel reservation by its reservation ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "reservation_id": {"type": "string", "description": "The hotel reservation ID (e.g. 'HR-0001')"},
        },
        "required": ["reservation_id"],
    },
}

# ---------------------------------------------------------------------------
# Car rental tools
# ---------------------------------------------------------------------------

SEARCH_CAR_RENTALS: dict[str, Any] = {
    "type": "function",
    "name": "search_car_rentals",
    "description": "Search for available car rentals at a location. Filter by dates, car class, and daily rate.",
    "parameters": {
        "type": "object",
        "properties": {
            "pickup_location": {"type": "string", "description": "Pickup location airport code (e.g. 'LHR', 'MIA')"},
            "pickup_date": {"type": "string", "description": "Pickup date in YYYY-MM-DD format"},
            "dropoff_date": {"type": "string", "description": "Dropoff date in YYYY-MM-DD format"},
            "car_class": {
                "type": "string",
                "enum": ["economy", "midsize", "suv", "luxury"],
                "description": "Filter by car class",
            },
            "max_daily_rate": {
                "type": "integer",
                "description": "Maximum daily rate in USD. Use -1 for no limit.",
            },
        },
        "required": ["pickup_location"],
    },
}

GET_CAR_RENTAL: dict[str, Any] = {
    "type": "function",
    "name": "get_car_rental",
    "description": "Retrieve the details of an existing car rental by its rental ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "rental_id": {"type": "string", "description": "The car rental ID (e.g. 'CR-0001')"},
        },
        "required": ["rental_id"],
    },
}

# ---------------------------------------------------------------------------
# All schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    GET_USER_DETAILS,
    GET_USER_RESERVATIONS,
    GET_BOOKING,
    GET_FLIGHT_STATUS,
    UPDATE_BOOKING,
    CANCEL_BOOKING,
    SEARCH_HOTELS,
    BOOK_HOTEL,
    GET_HOTEL_RESERVATION,
    SEARCH_CAR_RENTALS,
    GET_CAR_RENTAL,
]

WRITE_TOOL_NAMES: list[str] = [
    "update_booking",
    "cancel_booking",
    "book_hotel",
]
