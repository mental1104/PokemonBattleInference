"""定义租户配置预设与显示偏好的 SQLAlchemy 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.persistence.base import RuntimeBase


class StatConfigurationModel(RuntimeBase):
    """保存租户共享的自定义宝可梦能力配置。

    内置配置只存在于 application 注册表，本表仅保存可编辑的租户自定义配置。删除使用
    ``is_deleted`` 软删除，避免已提交任务的快照解释被历史配置清理影响。
    """

    __tablename__ = "stat_configurations"
    __table_args__ = (
        CheckConstraint("char_length(name) BETWEEN 1 AND 48", name="stat_configurations_name_len_ck"),
        CheckConstraint(
            "role IN ('attacker', 'defender', 'both')",
            name="stat_configurations_role_ck",
        ),
        CheckConstraint(
            "binding_kind IN ('global', 'pokemon')",
            name="stat_configurations_binding_kind_ck",
        ),
        CheckConstraint(
            "(binding_kind = 'global' AND pokemon_id IS NULL) OR "
            "(binding_kind = 'pokemon' AND pokemon_id IS NOT NULL AND pokemon_id > 0)",
            name="stat_configurations_binding_ck",
        ),
        CheckConstraint(
            "ev_hp BETWEEN 0 AND 252 AND ev_attack BETWEEN 0 AND 252 AND "
            "ev_defense BETWEEN 0 AND 252 AND ev_special_attack BETWEEN 0 AND 252 AND "
            "ev_special_defense BETWEEN 0 AND 252 AND ev_speed BETWEEN 0 AND 252",
            name="stat_configurations_ev_each_ck",
        ),
        CheckConstraint(
            "ev_hp + ev_attack + ev_defense + ev_special_attack + ev_special_defense + ev_speed <= 510",
            name="stat_configurations_ev_total_ck",
        ),
        CheckConstraint(
            "iv_hp BETWEEN 0 AND 31 AND iv_attack BETWEEN 0 AND 31 AND "
            "iv_defense BETWEEN 0 AND 31 AND iv_special_attack BETWEEN 0 AND 31 AND "
            "iv_special_defense BETWEEN 0 AND 31 AND iv_speed BETWEEN 0 AND 31",
            name="stat_configurations_iv_each_ck",
        ),
        Index("stat_configurations_tenant_role_idx", "tenant_id", "role", "is_deleted"),
        Index("stat_configurations_tenant_pokemon_idx", "tenant_id", "binding_kind", "pokemon_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(48), nullable=False)
    nature_id: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    binding_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    pokemon_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ev_hp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ev_attack: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ev_defense: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ev_special_attack: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ev_special_defense: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ev_speed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    iv_hp: Mapped[int] = mapped_column(Integer, nullable=False, default=31)
    iv_attack: Mapped[int] = mapped_column(Integer, nullable=False, default=31)
    iv_defense: Mapped[int] = mapped_column(Integer, nullable=False, default=31)
    iv_special_attack: Mapped[int] = mapped_column(Integer, nullable=False, default=31)
    iv_special_defense: Mapped[int] = mapped_column(Integer, nullable=False, default=31)
    iv_speed: Mapped[int] = mapped_column(Integer, nullable=False, default=31)
    is_deleted: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StatConfigurationPreferenceModel(RuntimeBase):
    """保存租户对内置和自定义配置的显示偏好。"""

    __tablename__ = "stat_configuration_preferences"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "role",
            "reference_type",
            "reference_key",
            name="stat_configuration_preferences_ref_uq",
        ),
        CheckConstraint(
            "role IN ('attacker', 'defender')",
            name="stat_configuration_preferences_role_ck",
        ),
        CheckConstraint(
            "reference_type IN ('builtin', 'custom')",
            name="stat_configuration_preferences_ref_type_ck",
        ),
        CheckConstraint("sort_order >= 0", name="stat_configuration_preferences_sort_ck"),
        Index("stat_configuration_preferences_tenant_role_idx", "tenant_id", "role", "sort_order"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_key: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hidden: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = ["StatConfigurationModel", "StatConfigurationPreferenceModel"]
