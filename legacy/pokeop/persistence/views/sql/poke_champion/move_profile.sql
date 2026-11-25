WITH champion_moves AS (
    SELECT DISTINCT pm.move_id
    FROM poke_raw.pokemon_moves pm
    JOIN poke_champion.ruleset_context_mv rc
        ON rc.version_group_id = pm.version_group_id
),
move_values AS (
    SELECT
        rc.ruleset_id,
        rc.generation_id,
        rc.version_group_id,
        m.id AS move_id,
        m.identifier AS move_identifier,
        COALESCE(old_type.type_id, m.type_id) AS type_id,
        COALESCE(old_power.power, m.power) AS power,
        COALESCE(old_pp.pp, m.pp) AS pp,
        COALESCE(old_accuracy.accuracy, m.accuracy) AS accuracy,
        COALESCE(old_priority.priority, NULLIF(m.priority, '')::integer) AS priority,
        COALESCE(old_target.target_id, m.target_id) AS target_id,
        m.damage_class_id,
        COALESCE(old_effect.effect_id, m.effect_id) AS effect_id,
        COALESCE(old_effect_chance.effect_chance, m.effect_chance) AS effect_chance
    FROM champion_moves cm
    JOIN poke_champion.ruleset_context_mv rc
        ON true
    JOIN poke_raw.moves m
        ON m.id = cm.move_id
    LEFT JOIN LATERAL (
        SELECT NULLIF(mc.type_id, 0) AS type_id
        FROM poke_raw.move_changelog mc
        JOIN poke_raw.version_groups changed_vg
            ON changed_vg.id = mc.changed_in_version_group_id
        WHERE mc.move_id = m.id
          AND changed_vg."order" > rc.version_group_order
          AND NULLIF(mc.type_id, 0) IS NOT NULL
        ORDER BY changed_vg."order"
        LIMIT 1
    ) old_type ON true
    LEFT JOIN LATERAL (
        SELECT NULLIF(mc.power, 0) AS power
        FROM poke_raw.move_changelog mc
        JOIN poke_raw.version_groups changed_vg
            ON changed_vg.id = mc.changed_in_version_group_id
        WHERE mc.move_id = m.id
          AND changed_vg."order" > rc.version_group_order
          AND NULLIF(mc.power, 0) IS NOT NULL
        ORDER BY changed_vg."order"
        LIMIT 1
    ) old_power ON true
    LEFT JOIN LATERAL (
        SELECT NULLIF(mc.pp, 0) AS pp
        FROM poke_raw.move_changelog mc
        JOIN poke_raw.version_groups changed_vg
            ON changed_vg.id = mc.changed_in_version_group_id
        WHERE mc.move_id = m.id
          AND changed_vg."order" > rc.version_group_order
          AND NULLIF(mc.pp, 0) IS NOT NULL
        ORDER BY changed_vg."order"
        LIMIT 1
    ) old_pp ON true
    LEFT JOIN LATERAL (
        SELECT NULLIF(mc.accuracy, 0) AS accuracy
        FROM poke_raw.move_changelog mc
        JOIN poke_raw.version_groups changed_vg
            ON changed_vg.id = mc.changed_in_version_group_id
        WHERE mc.move_id = m.id
          AND changed_vg."order" > rc.version_group_order
          AND NULLIF(mc.accuracy, 0) IS NOT NULL
        ORDER BY changed_vg."order"
        LIMIT 1
    ) old_accuracy ON true
    LEFT JOIN LATERAL (
        SELECT NULLIF(mc.priority, '')::integer AS priority
        FROM poke_raw.move_changelog mc
        JOIN poke_raw.version_groups changed_vg
            ON changed_vg.id = mc.changed_in_version_group_id
        WHERE mc.move_id = m.id
          AND changed_vg."order" > rc.version_group_order
          AND NULLIF(mc.priority, '') IS NOT NULL
        ORDER BY changed_vg."order"
        LIMIT 1
    ) old_priority ON true
    LEFT JOIN LATERAL (
        SELECT NULLIF(mc.target_id, 0) AS target_id
        FROM poke_raw.move_changelog mc
        JOIN poke_raw.version_groups changed_vg
            ON changed_vg.id = mc.changed_in_version_group_id
        WHERE mc.move_id = m.id
          AND changed_vg."order" > rc.version_group_order
          AND NULLIF(mc.target_id, 0) IS NOT NULL
        ORDER BY changed_vg."order"
        LIMIT 1
    ) old_target ON true
    LEFT JOIN LATERAL (
        SELECT NULLIF(mc.effect_id, 0) AS effect_id
        FROM poke_raw.move_changelog mc
        JOIN poke_raw.version_groups changed_vg
            ON changed_vg.id = mc.changed_in_version_group_id
        WHERE mc.move_id = m.id
          AND changed_vg."order" > rc.version_group_order
          AND NULLIF(mc.effect_id, 0) IS NOT NULL
        ORDER BY changed_vg."order"
        LIMIT 1
    ) old_effect ON true
    LEFT JOIN LATERAL (
        SELECT NULLIF(mc.effect_chance, 0) AS effect_chance
        FROM poke_raw.move_changelog mc
        JOIN poke_raw.version_groups changed_vg
            ON changed_vg.id = mc.changed_in_version_group_id
        WHERE mc.move_id = m.id
          AND changed_vg."order" > rc.version_group_order
          AND NULLIF(mc.effect_chance, 0) IS NOT NULL
        ORDER BY changed_vg."order"
        LIMIT 1
    ) old_effect_chance ON true
)
SELECT
    mv.ruleset_id,
    mv.generation_id,
    mv.version_group_id,
    mv.move_id,
    mv.move_identifier,
    mn.name AS move_name,
    mv.type_id,
    t.identifier AS type_identifier,
    tn.name AS type_name,
    mv.power,
    mv.pp,
    mv.accuracy,
    mv.priority,
    mv.target_id,
    mt.identifier AS target_identifier,
    mv.damage_class_id,
    mdc.identifier AS damage_class_identifier,
    mv.effect_id,
    mv.effect_chance
FROM move_values mv
JOIN poke_champion.ruleset_context_mv rc
    ON rc.ruleset_id = mv.ruleset_id
LEFT JOIN poke_raw.move_names mn
    ON mn.move_id = mv.move_id
   AND mn.local_language_id = rc.language_id
LEFT JOIN poke_raw.types t
    ON t.id = mv.type_id
LEFT JOIN poke_raw.type_names tn
    ON tn.type_id = mv.type_id
   AND tn.local_language_id = rc.language_id
LEFT JOIN poke_raw.move_targets mt
    ON mt.id = mv.target_id
LEFT JOIN poke_raw.move_damage_classes mdc
    ON mdc.id = mv.damage_class_id

