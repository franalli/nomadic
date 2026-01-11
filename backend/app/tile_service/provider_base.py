from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from app.schemas import Tile

from .models import SearchContext


class Provider(ABC):
    """
    Base class for tile providers (Booking.com, Expedia, etc.).
    Each provider implements `search` and returns normalized Tiles.
    """

    name: str

    @abstractmethod
    def search(self, ctx: SearchContext) -> List[Tile]:
        """
        Perform a search for tiles based on the given context.
        Implementations should:
        - Call their underlying API / data source
        - Map results into Tile objects
        - Not worry about global ranking/merging
        """
        ...


# =============================================================================
# BOOKING PROVIDER INTERFACE (MVP Scaffolding)
# =============================================================================
#
# This section defines the interface for providers that support booking execution.
# Currently a placeholder for when real provider APIs (Expedia, Amadeus, Booking.com)
# are integrated.
#
# KEY DESIGN DECISIONS:
# 1. Booking is separate from tile search - different concerns, different auth
# 2. Booking happens via REST endpoints, NOT LangGraph nodes
# 3. Financial transactions need explicit user consent (no auto-booking)
# 4. Each provider may have different booking flows (redirect vs. embedded)
#
# WHEN IMPLEMENTING REAL PROVIDERS:
# - Expedia: Uses affiliate API, typically redirect-based booking
# - Amadeus: Direct API booking with payment tokenization
# - Booking.com: Affiliate program with deep links or API booking
# - Viator (activities): API booking with confirmation codes
#
# =============================================================================


class BookingFlowType(str, Enum):
    """
    The type of booking flow supported by a provider.

    REDIRECT: User is redirected to partner site to complete booking.
              We receive a commission/tracking callback.
              Example: Most affiliate programs (Booking.com, Expedia affiliates)

    EMBEDDED: Booking happens entirely within our app via API calls.
              We handle payment collection and pass to provider.
              Example: Amadeus direct booking, Stripe-integrated providers

    HYBRID: Initial search/hold is API-based, but payment redirects to partner.
            Example: Some OTAs allow API hold but require redirect for payment
    """

    REDIRECT = "redirect"
    EMBEDDED = "embedded"
    HYBRID = "hybrid"


class BookingStatus(str, Enum):
    """
    Status of a booking session.

    INITIATED: Booking request received, awaiting user action or payment
    PENDING_PAYMENT: Awaiting payment confirmation (for embedded flow)
    HOLD: Inventory is temporarily held (expires after X minutes)
    CONFIRMED: Booking is confirmed, confirmation code issued
    FAILED: Booking failed (payment declined, inventory unavailable, etc.)
    CANCELLED: User or system cancelled the booking
    EXPIRED: Hold or session expired before completion
    """

    INITIATED = "initiated"
    PENDING_PAYMENT = "pending_payment"
    HOLD = "hold"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class BookingSession:
    """
    Represents an in-progress booking session.

    This is returned when a user initiates a booking. Depending on the provider's
    flow_type, the frontend will either:
    - REDIRECT: Navigate user to redirect_url
    - EMBEDDED: Show payment form and call confirm_booking()
    - HYBRID: Show hold confirmation, then redirect for payment

    REAL PROVIDER IMPLEMENTATION NOTES:
    - session_id should be provider-specific and stored in our DB
    - hold_expires_at is critical for inventory management
    - provider_data stores any provider-specific state needed for confirmation
    """

    session_id: str
    status: BookingStatus
    flow_type: BookingFlowType
    tile_id: str  # The tile being booked
    provider_name: str

    # For REDIRECT flow: where to send the user
    # Example: "https://booking.com/checkout?affiliate_id=xxx&session=yyy"
    redirect_url: Optional[str] = None

    # For EMBEDDED flow: form fields required for payment
    # Example: {"requires_card": True, "requires_billing_address": True}
    payment_form_config: Optional[Dict[str, Any]] = None

    # When the hold expires (if provider supports holds)
    # Frontend should show countdown and warn user
    hold_expires_at: Optional[datetime] = None

    # Provider-specific data needed for confirmation
    # IMPORTANT: This may contain sensitive data - do not expose to frontend
    # Example: {"amadeus_order_id": "xxx", "pnr": "ABC123"}
    provider_data: Dict[str, Any] = field(default_factory=dict)

    # Price at time of booking initiation (may differ from tile estimate)
    confirmed_price: Optional[float] = None
    currency: str = "USD"

    # Human-readable messages for the user
    user_message: Optional[str] = None


@dataclass
class BookingConfirmation:
    """
    Result of a completed booking.

    Returned after successful payment/confirmation. Contains all information
    needed to display a receipt and allow the user to manage their booking.

    REAL PROVIDER IMPLEMENTATION NOTES:
    - confirmation_code is the provider's booking reference
    - Always store full provider_response for debugging/disputes
    - cancellation_policy is critical for user experience
    - deep_link_manage should point to the provider's booking management page
    """

    session_id: str
    status: BookingStatus  # Should be CONFIRMED or FAILED
    confirmation_code: Optional[str] = None  # e.g., "BK-12345678"

    # Booking details
    tile_id: str = ""
    provider_name: str = ""
    final_price: float = 0.0
    currency: str = "USD"

    # Traveler information (echoed back for confirmation)
    traveler_name: Optional[str] = None
    traveler_email: Optional[str] = None

    # Dates and details
    check_in: Optional[str] = None  # ISO date for hotels
    check_out: Optional[str] = None
    departure_date: Optional[str] = None  # For flights
    activity_date: Optional[str] = None  # For activities

    # Cancellation policy summary
    # Example: "Free cancellation until Dec 15, 2024"
    cancellation_policy: Optional[str] = None
    is_refundable: bool = False

    # Link to manage booking on provider's site
    deep_link_manage: Optional[str] = None

    # Full provider response (for debugging, stored in DB but not sent to frontend)
    provider_response: Dict[str, Any] = field(default_factory=dict)

    # Error information if booking failed
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class TravelerInfo:
    """
    Traveler information required for booking.

    REAL PROVIDER IMPLEMENTATION NOTES:
    - Different providers require different fields
    - Flights typically need passport info for international travel
    - Hotels may only need name and email
    - Validate required fields based on provider requirements
    """

    # Basic info (required for all providers)
    first_name: str
    last_name: str
    email: str

    # Contact (usually required)
    phone: Optional[str] = None

    # Passport info (required for international flights)
    # IMPORTANT: Handle with care - PII data
    passport_number: Optional[str] = None
    passport_country: Optional[str] = None
    passport_expiry: Optional[str] = None  # ISO date

    # Date of birth (required by some providers)
    date_of_birth: Optional[str] = None  # ISO date

    # Address (required for some payment methods)
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None

    # Special requests
    special_requests: Optional[str] = None


class BookableProvider(Provider):
    """
    Abstract base class for providers that support booking execution.

    Extends the basic Provider with booking capabilities. Not all providers
    need to implement this - some are search-only (e.g., price comparison).

    IMPLEMENTATION CHECKLIST FOR REAL PROVIDERS:
    1. Implement search() from Provider base class
    2. Set flow_type to indicate booking flow (redirect/embedded/hybrid)
    3. Implement initiate_booking() to start booking process
    4. Implement confirm_booking() for embedded/hybrid flows
    5. Implement cancel_booking() for post-booking cancellation
    6. Implement get_booking_status() for status checks
    7. Handle authentication (API keys, OAuth tokens, etc.)
    8. Implement rate limiting and retry logic
    9. Log all booking attempts for audit trail

    EXAMPLE REAL IMPLEMENTATION (Amadeus):
    ```python
    class AmadeusProvider(BookableProvider):
        flow_type = BookingFlowType.EMBEDDED

        async def initiate_booking(self, tile, traveler, payment_intent):
            # 1. Create Amadeus order with traveler details
            # 2. Get price confirmation (may differ from estimate)
            # 3. Create payment intent with Stripe
            # 4. Return session with payment form config
            order = await self.amadeus_client.create_order(...)
            return BookingSession(
                session_id=order.id,
                status=BookingStatus.PENDING_PAYMENT,
                flow_type=self.flow_type,
                payment_form_config={"stripe_client_secret": "..."},
                confirmed_price=order.price,
            )
    ```
    """

    # Subclasses must set this to indicate their booking flow type
    flow_type: BookingFlowType = BookingFlowType.REDIRECT

    @abstractmethod
    async def initiate_booking(
        self,
        tile: Tile,
        traveler: TravelerInfo,
        payment_intent: Optional[Dict[str, Any]] = None,
    ) -> BookingSession:
        """
        Start the booking process for a tile.

        This is called when user clicks "Book" on a tile. Depending on flow_type:
        - REDIRECT: Returns a session with redirect_url to partner checkout
        - EMBEDDED: Returns a session with payment_form_config for in-app payment
        - HYBRID: Returns a session with both (show details, then redirect)

        Args:
            tile: The tile to book (contains all search context)
            traveler: Traveler information (may be partial for redirect flow)
            payment_intent: Optional payment data for embedded flow
                           Example: {"stripe_payment_method_id": "pm_xxx"}

        Returns:
            BookingSession with next steps for the frontend

        Raises:
            BookingError: If booking cannot be initiated (inventory, validation, etc.)

        PLACEHOLDER IMPLEMENTATION:
        This method should be implemented by each real provider.
        See class docstring for implementation example.
        """
        ...

    @abstractmethod
    async def confirm_booking(
        self,
        session_id: str,
        payment_confirmation: Optional[Dict[str, Any]] = None,
    ) -> BookingConfirmation:
        """
        Complete a booking after payment (for embedded/hybrid flows).

        Called after user completes payment in embedded flow, or after
        receiving payment webhook callback. For redirect flows, this may
        be called from a webhook when partner notifies us of completion.

        Args:
            session_id: The booking session to confirm
            payment_confirmation: Payment details from payment processor
                                 Example: {"stripe_payment_intent_id": "pi_xxx"}

        Returns:
            BookingConfirmation with confirmation code and details

        Raises:
            BookingError: If confirmation fails (payment declined, expired, etc.)

        PLACEHOLDER IMPLEMENTATION:
        Real providers will:
        1. Verify payment was successful
        2. Call provider API to confirm booking
        3. Store confirmation in database
        4. Send confirmation email to traveler
        """
        ...

    async def cancel_booking(
        self,
        session_id: str,
        reason: Optional[str] = None,
    ) -> BookingConfirmation:
        """
        Cancel an existing booking.

        Called when user requests cancellation. Provider should check
        cancellation policy and apply any fees.

        Args:
            session_id: The booking session to cancel
            reason: Optional cancellation reason for logging

        Returns:
            BookingConfirmation with status=CANCELLED and refund details

        Raises:
            BookingError: If cancellation is not allowed or fails

        PLACEHOLDER IMPLEMENTATION:
        Default implementation raises NotImplementedError.
        Real providers should:
        1. Check cancellation policy (is it allowed? any fees?)
        2. Call provider API to cancel
        3. Process refund if applicable
        4. Update database records
        5. Send cancellation confirmation email
        """
        raise NotImplementedError(
            f"{self.name} does not support cancellation via API. "
            "User should cancel directly with the provider."
        )

    async def get_booking_status(
        self,
        session_id: str,
    ) -> BookingSession:
        """
        Check the current status of a booking session.

        Useful for:
        - Polling during async booking flows
        - Checking if a hold has expired
        - Verifying booking state after redirect

        Args:
            session_id: The booking session to check

        Returns:
            BookingSession with current status

        PLACEHOLDER IMPLEMENTATION:
        Default implementation raises NotImplementedError.
        Real providers should query their API for current status.
        """
        raise NotImplementedError(
            f"{self.name} does not support status polling. " "Status updates come via webhooks."
        )


class BookingError(Exception):
    """
    Exception raised when a booking operation fails.

    Provides structured error information for proper error handling
    and user-friendly error messages.

    USAGE:
    ```python
    raise BookingError(
        code="INVENTORY_UNAVAILABLE",
        message="This room is no longer available at the selected dates.",
        provider="booking_com",
        recoverable=True,  # User can try different dates
    )
    ```
    """

    def __init__(
        self,
        code: str,
        message: str,
        provider: Optional[str] = None,
        recoverable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            code: Machine-readable error code for frontend handling
                  Examples: "INVENTORY_UNAVAILABLE", "PAYMENT_DECLINED",
                           "HOLD_EXPIRED", "INVALID_TRAVELER_INFO"
            message: Human-readable error message for user display
            provider: Provider name for logging
            recoverable: Whether user can retry with modifications
            details: Additional error details for debugging
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.provider = provider
        self.recoverable = recoverable
        self.details = details or {}
