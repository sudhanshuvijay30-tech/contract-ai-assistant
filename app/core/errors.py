class ContractAssistantError(Exception):
    status_code = 500
    code = "contract_assistant_error"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class BadRequestError(ContractAssistantError):
    status_code = 400
    code = "bad_request"


class NotFoundError(ContractAssistantError):
    status_code = 404
    code = "not_found"


class AIProviderNotConfiguredError(ContractAssistantError):
    status_code = 503
    code = "ai_provider_not_configured"


class VectorStoreError(ContractAssistantError):
    status_code = 503
    code = "vector_store_error"

