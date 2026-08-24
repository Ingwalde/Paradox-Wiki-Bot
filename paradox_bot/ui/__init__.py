"""Presentation layer: everything the user sees.

Imports flow one way -- ui/ may import config and games, never bot.py or
cogs/. That is what keeps the views testable without a gateway connection.
"""
