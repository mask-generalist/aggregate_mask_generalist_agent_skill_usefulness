"""Tool schemas (OpenAI function calling format) for the travel environment.

17 tools: 10 READ, 7 WRITE.
"""

from typing import Any

# ---------------------------------------------------------------------------
# READ tools
# ---------------------------------------------------------------------------

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

GET_POLICIES: dict[str, Any] = {
    "type": "function",
    "name": "get_policies",
    "description": (
        "Look up travel policies for a specific topic. "
        "Topics: 'cancel' (flight cancellation rules), 'change' (flight change rules), "
        "'baggage' (baggage allowance by fare class and loyalty tier), "
        "'delay_compensation' (delay/cancellation compensation), "
        "'loyalty' (loyalty points redemption rates and rules), "
        "'upgrade' (cabin class upgrade eligibility and pricing), "
        "'hotel_cancel' (hotel reservation cancellation rules), "
        "'car_rental_cancel' (car rental cancellation rules)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "enum": [
                    "cancel",
                    "change",
                    "baggage",
                    "delay_compensation",
                    "loyalty",
                    "upgrade",
                    "hotel_cancel",
                    "car_rental_cancel",
                ],
                "description": "The policy topic to look up",
            },
            "cabin_class": {
                "type": "string",
                "enum": ["basic_economy", "economy", "business", "first"],
                "description": "The cabin class (affects cancellation/change/baggage/upgrade rules)",
            },
            "loyalty_tier": {
                "type": "string",
                "enum": ["basic", "silver", "gold", "platinum"],
                "description": "Customer loyalty tier (affects baggage allowance and points redemption rate)",
            },
            "route_type": {
                "type": "string",
                "enum": ["domestic", "international"],
                "description": "Route type (affects cancellation/change fees and free window duration)",
            },
        },
        "required": ["topic"],
    },
}

# ---------------------------------------------------------------------------
# WRITE tools
# ---------------------------------------------------------------------------

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

CANCEL_HOTEL_RESERVATION: dict[str, Any] = {
    "type": "function",
    "name": "cancel_hotel_reservation",
    "description": (
        "Cancel a hotel reservation. First call without confirm to preview the cancellation terms, "
        "then call with confirm=true to execute."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reservation_id": {"type": "string", "description": "The hotel reservation ID to cancel"},
            "confirm": {
                "type": "boolean",
                "description": "Confirm the cancellation after reviewing the terms.",
            },
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

BOOK_CAR_RENTAL: dict[str, Any] = {
    "type": "function",
    "name": "book_car_rental",
    "description": "Book a car rental option returned by search_car_rentals for a customer.",
    "parameters": {
        "type": "object",
        "properties": {
            "car_id": {"type": "string", "description": "Car rental option ID from search_car_rentals"},
            "user_id": {"type": "string", "description": "Customer user ID"},
        },
        "required": ["car_id", "user_id"],
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

CANCEL_CAR_RENTAL: dict[str, Any] = {
    "type": "function",
    "name": "cancel_car_rental",
    "description": (
        "Cancel a car rental. First call without confirm to preview the cancellation terms, "
        "then call with confirm=true to execute."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "rental_id": {"type": "string", "description": "The car rental ID to cancel"},
            "confirm": {
                "type": "boolean",
                "description": "Confirm the cancellation after reviewing the terms.",
            },
        },
        "required": ["rental_id"],
    },
}

# ---------------------------------------------------------------------------
# All schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    GET_USER_RESERVATIONS,
    GET_BOOKING,
    GET_POLICIES,
    CANCEL_BOOKING,
    BOOK_HOTEL,
    GET_HOTEL_RESERVATION,
    CANCEL_HOTEL_RESERVATION,
    SEARCH_CAR_RENTALS,
    BOOK_CAR_RENTAL,
    GET_CAR_RENTAL,
    CANCEL_CAR_RENTAL,
]

WRITE_TOOL_NAMES: list[str] = [
    "cancel_booking",
    "book_hotel",
    "cancel_hotel_reservation",
    "book_car_rental",
    "cancel_car_rental",
]
