"""The conversation email worker: processes outbox events and sends deliveries. Imports nothing from
FastAPI, so it can run embedded in the API (`EMBEDDED_WORKER`) or as `python -m
membership_management.worker`."""
