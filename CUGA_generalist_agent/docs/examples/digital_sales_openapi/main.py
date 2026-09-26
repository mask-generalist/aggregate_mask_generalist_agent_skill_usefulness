import random
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, Path, Query
from pydantic import BaseModel

# --- Pydantic Models ---


class Account(BaseModel):
    """Represents a single sales account."""

    id: str
    name: str
    state: str
    revenue: int
    is_third_party: bool = False  # New field to indicate if the account is from a third-party provider


class JobTitle(BaseModel):
    """Represents a job title."""

    title: str


class Contact(BaseModel):
    """Represents a contact person at an account."""

    id: str
    name: str
    email: str
    account_id: str
    job_title: str


class MyAccountsOutput(BaseModel):
    """Response model for getting a user's accounts."""

    accounts: List[Account]
    coverage_id: str
    client_status: str


class AccountsOutput(BaseModel):
    """Response model for getting a list of accounts."""

    accounts: List[Account]


class JobTitlesOutput(BaseModel):
    """Response model for getting a list of job titles."""

    job_titles: List[JobTitle]


class ContactsOutput(BaseModel):
    """Response model for getting a list of contacts."""

    contacts: List[Contact]


# --- Sample Data Generation ---

# A static list of 100 accounts for consistent testing
accounts_list_raw = [
    ("Apex Industries", "NY", 1200000),
    ("Starlight Corp", "FL", 300000),
    ("Phoenix Holdings", "CA", 9500000),
    ("Meridian Enterprises", "IL", 750000),
    ("Zenith Group", "TX", 4500000),
    ("Silverline Systems", "WA", 6800000),
    ("Frontier Tech", "CO", 2100000),
    ("Evergreen LLC", "OR", 900000),
    ("Innovate Inc.", "CA", 5500000),
    ("Data Flow Inc.", "TX", 7100000),
    ("Cloud Sphere LLC", "WA", 4300000),
    ("Net Weavers Corp", "NY", 2200000),
    ("Info Stream Tech", "CA", 8900000),
    ("Global Reach Inc.", "FL", 1500000),
    ("Terra Firm Ltd.", "CO", 3200000),
    ("Blue Ocean Co.", "CA", 6200000),
    ("Red River LLC", "TX", 500000),
    ("Golden Gate Group", "CA", 9800000),
    ("Keystone Industries", "PA", 3400000),
    ("Sunbeam Systems", "FL", 1800000),
    ("Crystal Clear Co.", "AZ", 2900000),
    ("Summit Strategies", "CO", 5300000),
    ("North Star Ent.", "MN", 4100000),
    ("Alpha Wave Tech", "WA", 7600000),
    ("Omega Solutions", "TX", 8300000),
    ("Delta Force Inc.", "GA", 2700000),
    ("Gamma Ray Group", "IL", 6400000),
    ("Echo Labs", "CA", 4900000),
    ("Bravo Corp", "NY", 1100000),
    ("Momentum Machines", "MI", 3800000),
    ("Velocity Ventures", "TX", 5900000),
    ("Pinnacle Partners", "IL", 7200000),
    ("Horizon Holdings", "FL", 2400000),
    ("Catalyst Creations", "CA", 8800000),
    ("Synergy Systems", "TX", 6700000),
    ("Vanguard Vision", "NY", 3300000),
    ("Triton Tech", "WA", 5100000),
    ("Orion Operations", "CO", 2600000),
    ("Helios Holdings", "FL", 400000),
    ("Titan Industries", "MI", 4800000),
    ("Matrix Methods", "IL", 7900000),
    ("Vertex Ventures", "CA", 9200000),
    ("Nexus Networks", "TX", 6100000),
    ("Spectrum Solutions", "NY", 1700000),
    ("Polaris Projects", "MN", 3600000),
    ("Quasar Queries", "AZ", 2300000),
    ("Stellar Systems", "WA", 5800000),
    ("Nebula Networks", "OR", 850000),
    ("Andromeda Inc.", "CA", 9700000),
    ("Cosmos Creations", "TX", 7400000),
    ("Galaxy Group", "FL", 1300000),
    ("Supernova Systems", "NY", 3000000),
    ("Blackhole Co.", "IL", 6900000),
    ("Rocket Corp", "FL", 2000000),
    ("Comet Co.", "CO", 1400000),
    ("Meteorite Methods", "AZ", 950000),
    ("Asteroid Ventures", "TX", 3700000),
    ("Planet Partners", "CA", 8100000),
    ("Starship Systems", "WA", 5600000),
    ("Warp Drive Inc.", "NY", 4200000),
    ("Teleport Tech", "CA", 7700000),
    ("Time Travel Co.", "IL", 6300000),
    ("Future Forward", "TX", 9000000),
    ("Next Gen Group", "WA", 4700000),
    ("Legacy Labs", "NY", 800000),
    ("Tradition Tech", "PA", 2500000),
    ("Old School Systems", "OH", 1900000),
    ("Heritage Holdings", "GA", 3100000),
    ("Pioneer Partners", "OR", 700000),
    ("Settler Solutions", "CO", 1600000),
    ("Homestead Inc.", "MN", 4400000),
    ("Frontier Flow", "TX", 5200000),
    ("Wild West Web", "AZ", 600000),
    ("Gold Rush Group", "CA", 9999999),
    ("Silicon Valley Co.", "CA", 9400000),
    ("Route 66 Systems", "IL", 3900000),
    ("Big Apple Biz", "NY", 8600000),
    ("Lone Star Logic", "TX", 9300000),
    ("Sunshine State Co.", "FL", 2800000),
    ("Windy City Web", "IL", 6600000),
    ("Badger State Biz", "WI", 3500000),
    ("Wolverine Web", "MI", 4600000),
    ("Buckeye Biz", "OH", 2000000),
    ("Empire State Ent.", "NY", 8400000),
    ("Golden State Group", "CA", 9600000),
    ("Evergreen Ent.", "WA", 5400000),
    ("Centennial Co.", "CO", 2200000),
    ("Beaver State Biz", "OR", 1000000),
    ("Grand Canyon Group", "AZ", 1200000),
    ("Silver State Systems", "NV", 1800000),
    ("Beehive Biz", "UT", 1500000),
    ("Gem State Group", "ID", 1100000),
    ("Big Sky Biz", "MT", 900000),
    ("Equality State Ent.", "WY", 700000),
    ("Cornhusker Co.", "NE", 1400000),
    ("Sunflower State", "KS", 1300000),
    ("Sooner State", "OK", 1700000),
    ("Show Me Systems", "MO", 2100000),
    ("Hawkeye Holdings", "IA", 1900000),
    ("North Star Inc.", "MN", 2300000),
]

# Use a fixed seed for reproducible random assignments
random.seed(42)

SAMPLE_ACCOUNTS: Dict[str, Account] = {
    f"acc_{i}": Account(
        id=f"acc_{i}",
        name=name,
        state=state,
        revenue=rev,
        is_third_party=(i % 2 == 0),  # Make every even-indexed account a third-party account
    )
    for i, (name, state, rev) in enumerate(accounts_list_raw, start=1)
}

# Job titles used for contacts
job_titles_list = [
    "Chief Executive Officer",
    "Chief Technology Officer",
    "Chief Financial Officer",
    "Vice President of Sales",
    "Director of Marketing",
    "Sales Manager",
    "Product Manager",
    "Account Executive",
    "Data Scientist",
    "Software Engineer",
]

first_names = ["Alice", "Bob", "Charlie", "Diana", "Ethan", "Fiona", "George", "Helen", "Ian", "Julia"]
last_names = ["Johnson", "Williams", "Davis", "Miller", "Garcia", "Rodriguez", "Wilson", "Martinez"]

# Generate contacts linked to accounts
SAMPLE_CONTACTS: Dict[str, Contact] = {}
contact_index = 1
for account_id, account in SAMPLE_ACCOUNTS.items():
    num_contacts = random.randint(1, 3)  # Each account has 1-3 contacts
    for _ in range(num_contacts):
        contact_id = f"con_{contact_index}"
        first_name = random.choice(first_names)
        last_name = random.choice(last_names)
        name = f"{first_name} {last_name}"
        email = f"{first_name.lower()}.{last_name.lower()}@{account.name.split(' ')[0].lower()}.com".replace(
            '.', ''
        )
        job_title = random.choice(job_titles_list)

        SAMPLE_CONTACTS[contact_id] = Contact(
            id=contact_id, name=name, email=email, account_id=account_id, job_title=job_title
        )
        contact_index += 1

# --- FastAPI App Initialization ---

app = FastAPI(
    title="Digital Sales Skills API (Stabilized)",
    description="An API for managing sales accounts, contacts, and campaigns.",
    version="2.0.0",
)

# --- API Endpoints ---


@app.get("/my-accounts", response_model=MyAccountsOutput, summary="Get My Territory Accounts")
async def get_my_accounts():
    """
    Retrieves a list of accounts that are specifically assigned to the current user's territory,
    providing consistent and predictable results for the user's account management.
    """
    # Simulate a user's territory by returning accounts with odd IDs
    my_accounts = [acc for acc_id, acc in SAMPLE_ACCOUNTS.items() if int(acc_id.split('_')[1]) % 2 != 0]

    return MyAccountsOutput(
        accounts=my_accounts,
        coverage_id="COV-001",
        client_status="Active",
    )


@app.get("/third-party-accounts", response_model=AccountsOutput, summary="Get Third-Party Accounts")
async def get_third_party_accounts(
    campaign_name: Optional[str] = Query(None, title="Optional filter by campaign name"),
):
    """
    Retrieves a list of accounts from a third-party provider, with optional filtering by campaign.

    If `campaign_name` is "Tech Transformation", it returns accounts with revenue over $5M.
    If `campaign_name` is "High Value Outreach", it returns accounts in CA or NY.
    Otherwise, it returns all third-party accounts.
    """
    third_party_accounts = [acc for acc in SAMPLE_ACCOUNTS.values() if acc.is_third_party]

    if campaign_name:
        if campaign_name.lower() == "tech transformation":
            filtered_accounts = [acc for acc in third_party_accounts if acc.revenue > 5000000]
            return AccountsOutput(accounts=filtered_accounts)
        elif campaign_name.lower() == "high value outreach":
            filtered_accounts = [acc for acc in third_party_accounts if acc.state in ["CA", "NY"]]
            return AccountsOutput(accounts=filtered_accounts)

    return AccountsOutput(accounts=third_party_accounts)


@app.get(
    "/accounts/{account_id}/job-titles",
    response_model=JobTitlesOutput,
    summary="Get Job Titles by Account ID",
)
async def get_job_titles_by_account(account_id: str = Path(..., title="The ID of the account")):
    """
    Retrieves all unique job titles associated with contacts at a specific account.
    """
    if account_id not in SAMPLE_ACCOUNTS:
        return JobTitlesOutput(job_titles=[])

    # Find all contacts for the given account ID
    account_contacts = [contact for contact in SAMPLE_CONTACTS.values() if contact.account_id == account_id]

    # Get unique job titles from these contacts
    unique_job_titles: Set[str] = {contact.job_title for contact in account_contacts}

    return JobTitlesOutput(job_titles=[JobTitle(title=jt) for jt in unique_job_titles])


@app.get("/contacts", response_model=ContactsOutput, summary="Get Contacts")
async def get_contacts(
    account_id: Optional[str] = Query(None, title="Optional filter by account ID"),
    job_title: Optional[str] = Query(None, title="Optional filter by job title"),
):
    """
    Retrieves a list of contacts, with optional filters for account ID and job title.
    """
    found_contacts = list(SAMPLE_CONTACTS.values())

    if account_id:
        found_contacts = [contact for contact in found_contacts if contact.account_id == account_id]

    if job_title:
        found_contacts = [
            contact for contact in found_contacts if contact.job_title.lower() == job_title.lower()
        ]

    return ContactsOutput(contacts=found_contacts)


# --- Test Functions ---

#
# async def test_get_top_account():
#     """Test case 1: Get top account by revenue from my accounts."""
#     my_accounts_data = await get_my_accounts()
#     my_accounts = my_accounts_data.accounts
#
#     if not my_accounts:
#         print("No accounts found in my territory.")
#         return
#
#     # Sort accounts by revenue in descending order and get the first one
#     top_account = sorted(my_accounts, key=lambda acc: acc.revenue, reverse=True)[0]
#
#     print("\n--- Test 1: Top Account in My Territory by Revenue ---")
#     print(f"Top Account: {top_account.name} (Revenue: ${top_account.revenue:,})")
#     print("-" * 50)
#
#
# async def test_get_tech_transformation_contacts():
#     """Test case 2: Get 'Vice President of Sales' contacts for Tech Transformation campaign."""
#     print("\n--- Test 2: 'VP of Sales' Contacts in 'Tech Transformation' Campaign ---")
#
#     # First, get third-party accounts for the "Tech Transformation" campaign
#     third_party_accounts_output = await get_third_party_accounts(campaign_name="Tech Transformation")
#     third_party_accounts = third_party_accounts_output.accounts
#
#     if not third_party_accounts:
#         print("No third-party accounts found for the 'Tech Transformation' campaign.")
#         return
#
#     # Now, get contacts for each of these accounts with the specific job title
#     all_contacts = []
#     for account in third_party_accounts:
#         contacts_output = await get_contacts(account_id=account.id, job_title="Vice President of Sales")
#         all_contacts.extend(contacts_output.contacts)
#
#     if all_contacts:
#         print(f"Found {len(all_contacts)} contacts:")
#         for contact in all_contacts:
#             print(f"- {contact.name}, {contact.job_title} at {SAMPLE_ACCOUNTS[contact.account_id].name}")
#     else:
#         print("No 'Vice President of Sales' contacts found for the selected accounts.")
#     print("-" * 50)

#
# async def test_get_my_accounts():
#     """Test case 3: Verify the 'my-accounts' endpoint behavior."""
#     print("\n--- Test 3: Verify 'my-accounts' Endpoint ---")
#
#     # Call the endpoint function
#     my_accounts_data = await get_my_accounts()
#     my_accounts = my_accounts_data.accounts
#
#     # Verify the response fields
#     print(f"Coverage ID: {my_accounts_data.coverage_id}")
#     print(f"Client Status: {my_accounts_data.client_status}")
#     print(f"Number of accounts found: {len(my_accounts)}")
#
#     # Verify expected values (based on the deterministic logic in the endpoint)
#     expected_count = 50
#     expected_coverage_id = "COV-001"
#     expected_client_status = "Active"
#
#     # Add a simple assertion-like check
#     if (
#         len(my_accounts) == expected_count
#         and my_accounts_data.coverage_id == expected_coverage_id
#         and my_accounts_data.client_status == expected_client_status
#     ):
#         print("Verification successful: All values match expectations.")
#     else:
#         print("Verification failed: Values do not match expectations.")
#
#     # Show a sample of the data to confirm it's not empty
#     if my_accounts:
#         print("\nExample of the first 6 accounts:")
#         for acc in my_accounts[:6]:
#             print(f" - {acc.name} (ID: {acc.id})")
#
#     print("-" * 50)


# --- Main entry point ---
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8888)
    # asyncio.run(test_get_top_account())
    # asyncio.run(test_get_tech_transformation_contacts())
    # asyncio.run(test_get_my_accounts())
