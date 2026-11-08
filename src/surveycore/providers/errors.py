from __future__ import annotations


class SurveyProviderStatusError(RuntimeError):
    pass


class SurveyPausedError(SurveyProviderStatusError):
    pass


class SurveyStoppedError(SurveyProviderStatusError):
    pass


class SurveyEnterpriseUnavailableError(SurveyProviderStatusError):
    pass


class SurveyNotOpenError(SurveyProviderStatusError):
    pass


class SubmissionVerificationRequiredError(RuntimeError):
    pass


class SubmitProxyUnavailableError(RuntimeError):
    pass


class SurveyProviderUnavailableAtRuntimeError(SurveyProviderStatusError):
    pass


__all__ = [
    "SubmissionVerificationRequiredError",
    "SubmitProxyUnavailableError",
    "SurveyEnterpriseUnavailableError",
    "SurveyNotOpenError",
    "SurveyPausedError",
    "SurveyProviderStatusError",
    "SurveyProviderUnavailableAtRuntimeError",
    "SurveyStoppedError",
]
