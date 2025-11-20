"""
PokemonBattleInference relies on the shared mental1104 PostgreSQL connector to avoid
duplicating boilerplate session management code.  This module simply re-exports the
pieces the application already depends on and keeps backwards-compatible helpers so
existing imports continue to work.
"""

from mental1104.connector import postgres as _postgres

Base = _postgres.Base
SessionAwareMixin = _postgres.SessionAwareMixin
open_session = _postgres.open_session
close_session = _postgres.close_session
get_session = _postgres.get_session
with_session = _postgres.with_session


def startup(create_tables: bool = True):
    """
    Maintain compatibility with the legacy signature by delegating to the shared
    connector's setup() helper, which accepts a create_tables flag.
    """
    return _postgres.setup(create_tables)


def setup(create_tables: bool = False):
    """
    Alias around the shared setup helper so application code can continue calling
    pokemon_battle_inference.infrastructure.db.setup().
    """
    return _postgres.setup(create_tables)
