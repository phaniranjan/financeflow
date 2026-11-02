class FinanceFlowError(Exception):
    """Base exception for all FinanceFlow domain and application errors."""


class EntityNotFoundError(FinanceFlowError):
    """Raised when an entity is not found in the persistence store."""


class BusinessNotFoundError(EntityNotFoundError):
    """Raised when a referenced Business cannot be found."""


class InvoiceNotFoundError(EntityNotFoundError):
    """Raised when a referenced Invoice cannot be found."""


class BusinessInactiveError(FinanceFlowError):
    """Raised when an operation requires an ACTIVE business but it is suspended or inactive."""


class DuplicateInvoiceNumberError(FinanceFlowError):
    """Raised when an invoice number already exists for a business."""


class InvalidInvoiceAmountError(FinanceFlowError):
    """Raised when an invoice amount violates positive financial invariant rules."""


class InvalidInvoiceDateError(FinanceFlowError):
    """Raised when invoice due date precedes issue date."""


class FinancingApplicationNotFoundError(EntityNotFoundError):
    """Raised when a referenced FinancingApplication cannot be found."""


class InvoiceNotEligibleError(FinanceFlowError):
    """Raised when an invoice is not eligible for financing."""


class DuplicateFinancingError(FinanceFlowError):
    """Raised when an active financing application already exists for an invoice."""


class InvalidFinancingAmountError(FinanceFlowError):
    """Raised when requested financing amount is invalid or exceeds invoice total."""


class InvalidFinancingTermsError(FinanceFlowError):
    """Raised when advance rate or fee rate violates acceptable bounds."""


class InvalidFinancingStateTransitionError(FinanceFlowError):
    """Raised when an illegal lifecycle transition is attempted on a financing application."""
