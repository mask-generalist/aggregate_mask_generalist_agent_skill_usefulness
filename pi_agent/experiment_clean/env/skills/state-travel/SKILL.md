---
name: state-travel
description: >-
  Travel booking & service. Use when acting as a customer-service agent for a travel company handling flight/hotel/car bookings, changes, cancellations, delays, fees, loyalty, and multi-product trip coordination.
  Provides a small stateful sandbox database and the domain tools via a CLI.
---

# Travel booking & service

You are a customer-service agent for a travel company handling flight/hotel/car bookings, changes, cancellations, delays, fees, loyalty, and multi-product trip coordination.

Today's date is **2026-06-15T10:00:00**. The customer you are serving is
identified in the task/conversation — extract their `user_id` from there (e.g.
"You are Elena Brooks (`user_7144 ff38`)") and pass it to any tool that requires
it. There is no default customer. Use the available tools to inspect state, apply the
correct policy, and take actions that update the database to the correct final state. Keep
customer-facing replies natural and direct. Do not reveal tool names or internal policy
categories to the customer; use them only to decide how to help.

## How this skill works

This skill is a **stateful domain over the unified per-task `world.db`** (SQLite at
`/workspace/world.db`, seeded fresh into `/workspace` by the runner before each task).
This skill reads/writes the rows scoped to it — flights and flight bookings tagged
`state-travel`, the users whose account names this skill, and their hotel/car
reservations, plus the shared hotel/car inventory catalogs. There is **no init step**
and no db.json seed:

1. Just **call tools**. Each call loads this skill's scoped slice from `world.db`,
   runs the tool, and writes any mutations straight back to `world.db`.
2. State persists across calls (it lives in `world.db`), including multi-step gates
   (policy-check → preview → confirm) tracked in a local `session.json`.
3. Read policy from [references/policies.md](references/policies.md) or the `get_policies` tool.
4. `python cli.py reset` clears this skill's session gates (the data itself is
   re-seeded per task by the runner). Point at a different DB with `CUGA_WORLD_DB`.

All commands are `python cli.py ...` (stdlib-only, no install).

## Accounts

Travel accounts are **seeded fresh per task** into `world.db` (scoped to this skill),
with randomized IDs and names — do **not** assume any fixed roster. Get the customer's
`user_id` from the task/conversation, then look up their details and reservations with
the read tools:

```bash
python cli.py call get_user_details --args '{"user_id":"<user_id>"}'
python cli.py call get_user_reservations --args '{"user_id":"<user_id>"}'
```

## CLI

```bash
# Dump the tool schemas (OpenAI function-calling format) + the write-tool list
python cli.py tools

# Call a tool (loads this skill's slice from world.db, then reads/mutates it)
python cli.py call get_policies --args '{"topic":"<topic>"}'

# Clear this skill's session gates (data is re-seeded per task by the runner)
python cli.py reset
```

The `call` result is JSON: `{"tool": ..., "is_write": bool, "result": <handler output>}`.
Errors are returned as `{"error": "..."}` with a non-zero exit code — read them and adjust.
Session gates live in `.state/session.json`; pass `--workspace <dir>` to relocate them,
and `--now <iso>` to override the date for a single call.

## Tools

**Read tools** (safe, no state change):
- `search_flights` — Search for available flights. Returns a list of matching flights with pricing for all cabin classes. Each flight includes a cabin_prices map (e.g. {economy: ...
- `get_user_details` — Look up a customer's account details including name, email, loyalty tier, and points balance.
- `get_user_reservations` — List all reservation IDs for a customer's flight bookings, hotel reservations, and car rentals. Use get_booking, get_hotel_reservation, or get_car_rental to ...
- `get_booking` — Retrieve the details of an existing booking by its booking ID.
- `get_flight_status` — Check the current status of a flight (scheduled, delayed, or cancelled).
- `get_policies` — Look up travel policies for a specific topic. Topics: 'cancel' (flight cancellation rules), 'change' (flight change rules), 'baggage' (baggage allowance by f...
- `search_hotels` — Search for available hotels in a city. Filter by dates, room type, and price.
- `get_hotel_reservation` — Retrieve the details of an existing hotel reservation by its reservation ID.
- `search_car_rentals` — Search for available car rentals at a location. Filter by dates, car class, and daily rate.
- `get_car_rental` — Retrieve the details of an existing car rental by its rental ID.

**Write tools** (mutate the database):
- `create_booking` — Book a flight for a customer. Requires flight_id, user_id, cabin_class, seat_type, meal_preference, add_wifi, add_extra_legroom, add_insurance, and payment_m...
- `update_booking` — Update an existing booking. Only pass the fields you want to change for same-flight edits. If you pass flight_id to change flights, you must also pass cabin_...
- `cancel_booking` — Cancel an existing booking. First call without confirm to preview the cancellation terms, then call with confirm=true to execute.
- `book_hotel` — Book a hotel option returned by search_hotels for a customer.
- `cancel_hotel_reservation` — Cancel a hotel reservation. First call without confirm to preview the cancellation terms, then call with confirm=true to execute.
- `book_car_rental` — Book a car rental option returned by search_car_rentals for a customer.
- `cancel_car_rental` — Cancel a car rental. First call without confirm to preview the cancellation terms, then call with confirm=true to execute.

## Operating procedure

1. **Gather** the relevant facts with read tools before acting.
2. **Check policy** with `get_policies` (some write tools require this first) and consult
   [references/policies.md](references/policies.md).
3. **Preview then confirm** for destructive/irreversible writes — many write tools use a
   two-step pattern (call once without `confirm`, then again with `confirm=true`). The
   agent owns any fee/refund math and must submit the computed amount.
4. **Verify** the final state with read tools.

## Workspace files (managed automatically)

- `/workspace/world.db` — the unified per-task SQLite store (this skill reads/writes its
  scoped rows; re-seeded fresh per task by the runner). Override with `CUGA_WORLD_DB`.
- `.state/session.json` — multi-step gate flags; managed automatically, do not edit.
