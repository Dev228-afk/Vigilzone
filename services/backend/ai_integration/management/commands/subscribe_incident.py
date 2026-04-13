"""Alias command for subscribe_incidents to support singular invocation."""

from .subscribe_incidents import Command as SubscribeIncidentsCommand


class Command(SubscribeIncidentsCommand):
    help = "Alias for subscribe_incidents"
