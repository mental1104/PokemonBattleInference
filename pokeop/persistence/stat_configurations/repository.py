"""实现租户配置预设的 PostgreSQL repository。"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any, TypeAlias
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from pokeop.application.use_cases.stat_configurations import (
    SaveStatConfigurationCommand,
    StatConfigurationError,
    StatConfigurationPreferenceRecord,
    StatConfigurationRecord,
    StatConfigurationReference,
)
from pokeop.domain.configuration_presets import (
    PokemonBindingKind,
    StatConfigurationRole,
    StatConfigurationSource,
    StatSpread,
    TenantScope,
)
from pokeop.persistence.stat_configurations.models import (
    StatConfigurationModel,
    StatConfigurationPreferenceModel,
)

TransactionFactory: TypeAlias = Callable[[], AbstractContextManager[Session]]


def _db_runtime() -> tuple[Any, Callable[[Any], AbstractContextManager[Session]]]:
    """延迟读取 common 数据库事务工厂。"""
    from mental1104.db import DBKind, tx_scope

    return DBKind, tx_scope


def _default_transaction_factory() -> AbstractContextManager[Session]:
    """创建一次 PostgreSQL 读写事务。"""
    db_kind, tx_scope = _db_runtime()
    return tx_scope(db_kind.POSTGRES)


class PostgresStatConfigurationRepository:
    """用 PostgreSQL 保存租户自定义配置和偏好。

    Args:
        transaction_factory: 返回 SQLAlchemy Session 事务上下文的工厂；测试可注入 SQLite
            或 PostgreSQL sessionmaker 包装器。
    """

    def __init__(self, transaction_factory: TransactionFactory | None = None) -> None:
        """保存事务工厂。"""
        self._transaction_factory = transaction_factory or _default_transaction_factory

    def list_custom(self, scope: TenantScope) -> tuple[StatConfigurationRecord, ...]:
        """列出当前租户全部自定义配置记录。"""
        with self._transaction_factory() as session:
            rows = session.execute(
                select(StatConfigurationModel)
                .where(StatConfigurationModel.tenant_id == scope.tenant_id)
                .order_by(StatConfigurationModel.created_at, StatConfigurationModel.id)
            ).scalars()
            return tuple(_record_from_model(row) for row in rows)

    def get_custom(self, scope: TenantScope, config_id: str) -> StatConfigurationRecord | None:
        """读取当前租户的一条自定义配置。"""
        with self._transaction_factory() as session:
            row = session.get(StatConfigurationModel, config_id)
            if row is None or row.tenant_id != scope.tenant_id:
                return None
            return _record_from_model(row)

    def create_custom(
        self,
        scope: TenantScope,
        command: SaveStatConfigurationCommand,
    ) -> StatConfigurationRecord:
        """创建一条租户共享自定义配置。"""
        now = _now()
        model = StatConfigurationModel(
            id=str(uuid4()),
            tenant_id=scope.tenant_id,
            name=command.name.strip(),
            nature_id=command.nature_id,
            role=command.role.value,
            binding_kind=command.binding_kind.value,
            pokemon_id=command.pokemon_id,
            created_at=now,
            updated_at=now,
            **_spread_columns(command.evs, "ev"),
            **_spread_columns(command.ivs, "iv"),
        )
        with self._transaction_factory() as session:
            session.add(model)
            session.flush()
            return _record_from_model(model)

    def update_custom(
        self,
        scope: TenantScope,
        config_id: str,
        command: SaveStatConfigurationCommand,
    ) -> StatConfigurationRecord:
        """完整更新当前租户的一条自定义配置。"""
        with self._transaction_factory() as session:
            model = session.get(StatConfigurationModel, config_id)
            if model is None or model.tenant_id != scope.tenant_id or model.is_deleted:
                raise StatConfigurationError("custom configuration not found")
            model.name = command.name.strip()
            model.nature_id = command.nature_id
            model.role = command.role.value
            model.binding_kind = command.binding_kind.value
            model.pokemon_id = command.pokemon_id
            for key, value in _spread_columns(command.evs, "ev").items():
                setattr(model, key, value)
            for key, value in _spread_columns(command.ivs, "iv").items():
                setattr(model, key, value)
            model.updated_at = _now()
            session.flush()
            return _record_from_model(model)

    def soft_delete_custom(self, scope: TenantScope, config_id: str) -> None:
        """软删除当前租户配置。"""
        with self._transaction_factory() as session:
            model = session.get(StatConfigurationModel, config_id)
            if model is None or model.tenant_id != scope.tenant_id or model.is_deleted:
                raise StatConfigurationError("custom configuration not found")
            model.is_deleted = True
            model.updated_at = _now()
            session.flush()

    def list_preferences(self, scope: TenantScope) -> tuple[StatConfigurationPreferenceRecord, ...]:
        """列出当前租户全部显示偏好。"""
        with self._transaction_factory() as session:
            rows = session.execute(
                select(StatConfigurationPreferenceModel)
                .where(StatConfigurationPreferenceModel.tenant_id == scope.tenant_id)
                .order_by(StatConfigurationPreferenceModel.role, StatConfigurationPreferenceModel.sort_order)
            ).scalars()
            return tuple(_preference_from_model(row) for row in rows)

    def save_preference(
        self,
        scope: TenantScope,
        *,
        role: StatConfigurationRole,
        reference_type: StatConfigurationSource,
        reference_key: str,
        sort_order: int,
        hidden: bool,
    ) -> StatConfigurationPreferenceRecord:
        """幂等保存一条显示偏好。"""
        with self._transaction_factory() as session:
            row = _upsert_preference(
                session,
                scope=scope,
                role=role,
                reference_type=reference_type,
                reference_key=reference_key,
                sort_order=sort_order,
                hidden=hidden,
            )
            return _preference_from_model(row)

    def save_order(
        self,
        scope: TenantScope,
        *,
        role: StatConfigurationRole,
        ordered_references: tuple[StatConfigurationReference, ...],
    ) -> None:
        """在单一事务中保存当前角色的完整排序偏好。"""
        with self._transaction_factory() as session:
            for index, reference in enumerate(ordered_references):
                _upsert_preference(
                    session,
                    scope=scope,
                    role=role,
                    reference_type=reference.source,
                    reference_key=reference.key,
                    sort_order=index,
                    hidden=False,
                )
            session.flush()


def _upsert_preference(
    session: Session,
    *,
    scope: TenantScope,
    role: StatConfigurationRole,
    reference_type: StatConfigurationSource,
    reference_key: str,
    sort_order: int,
    hidden: bool,
) -> StatConfigurationPreferenceModel:
    """用 PostgreSQL upsert 保存偏好；测试 SQLite 会退化为先查后写。"""
    now = _now()
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = (
            pg_insert(StatConfigurationPreferenceModel)
            .values(
                tenant_id=scope.tenant_id,
                role=role.value,
                reference_type=reference_type.value,
                reference_key=reference_key,
                sort_order=sort_order,
                hidden=hidden,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="stat_configuration_preferences_ref_uq",
                set_={"sort_order": sort_order, "hidden": hidden, "updated_at": now},
            )
            .returning(StatConfigurationPreferenceModel)
        )
        return session.execute(statement).scalar_one()

    row = session.execute(
        select(StatConfigurationPreferenceModel).where(
            StatConfigurationPreferenceModel.tenant_id == scope.tenant_id,
            StatConfigurationPreferenceModel.role == role.value,
            StatConfigurationPreferenceModel.reference_type == reference_type.value,
            StatConfigurationPreferenceModel.reference_key == reference_key,
        )
    ).scalar_one_or_none()
    if row is None:
        row = StatConfigurationPreferenceModel(
            tenant_id=scope.tenant_id,
            role=role.value,
            reference_type=reference_type.value,
            reference_key=reference_key,
            sort_order=sort_order,
            hidden=hidden,
            updated_at=now,
        )
        session.add(row)
    else:
        row.sort_order = sort_order
        row.hidden = hidden
        row.updated_at = now
    session.flush()
    return row


def _record_from_model(model: StatConfigurationModel) -> StatConfigurationRecord:
    """把 ORM model 转成 application record，隔离 SQLAlchemy 状态。"""
    return StatConfigurationRecord(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        nature_id=model.nature_id,
        evs=StatSpread.evs(
            hp=model.ev_hp,
            attack=model.ev_attack,
            defense=model.ev_defense,
            special_attack=model.ev_special_attack,
            special_defense=model.ev_special_defense,
            speed=model.ev_speed,
        ),
        ivs=StatSpread.ivs(
            hp=model.iv_hp,
            attack=model.iv_attack,
            defense=model.iv_defense,
            special_attack=model.iv_special_attack,
            special_defense=model.iv_special_defense,
            speed=model.iv_speed,
        ),
        role=StatConfigurationRole(model.role),
        binding_kind=PokemonBindingKind(model.binding_kind),
        pokemon_id=model.pokemon_id,
        is_deleted=model.is_deleted,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _preference_from_model(model: StatConfigurationPreferenceModel) -> StatConfigurationPreferenceRecord:
    """把偏好 ORM model 转成 application record。"""
    return StatConfigurationPreferenceRecord(
        tenant_id=model.tenant_id,
        role=StatConfigurationRole(model.role),
        reference_type=StatConfigurationSource(model.reference_type),
        reference_key=model.reference_key,
        sort_order=model.sort_order,
        hidden=model.hidden,
        updated_at=model.updated_at,
    )


def _spread_columns(spread: StatSpread, prefix: str) -> dict[str, int]:
    """把六项能力值转换为 ORM 列名。"""
    return {
        f"{prefix}_hp": spread.hp,
        f"{prefix}_attack": spread.attack,
        f"{prefix}_defense": spread.defense,
        f"{prefix}_special_attack": spread.special_attack,
        f"{prefix}_special_defense": spread.special_defense,
        f"{prefix}_speed": spread.speed,
    }


def _now() -> datetime:
    """返回带时区当前时间，避免 Python 写入 naive datetime。"""
    return datetime.now(timezone.utc)


__all__ = ["PostgresStatConfigurationRepository"]
