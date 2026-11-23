"""The email worker (conversation and report submitted emails): processes outbox events, each by its
event type's consumer, and sends deliveries. Imports nothing from
FastAPI, so it can run embedded in the API (`EMBEDDED_WORKER`) or as `python -m
membership_management.worker`."""
