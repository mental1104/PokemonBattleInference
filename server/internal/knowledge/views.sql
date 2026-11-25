-- Generated from owning materialized-view registry and SQL.
CREATE SCHEMA IF NOT EXISTS poke_champion;

CREATE MATERIALIZED VIEW IF NOT EXISTS poke_champion.ruleset_context_mv AS
SELECT
    'pokemon-champion'::text AS ruleset_id,
    'Pokemon Champion'::text AS ruleset_name,
    9::integer AS generation_id,
    25::integer AS version_group_id,
    12::integer AS language_id,
    vg.identifier AS version_group_identifier,
    vg."order" AS version_group_order,
    g.identifier AS generation_identifier
FROM poke_raw.version_groups vg
JOIN poke_raw.generations g
    ON g.id = vg.generation_id
WHERE vg.id = 25
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS ruleset_context_mv_pk ON poke_champion.ruleset_context_mv (ruleset_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS poke_champion.pokemon_profile_mv AS
WITH champion_pokemon AS (
    SELECT DISTINCT pm.pokemon_id
    FROM poke_raw.pokemon_moves pm
    JOIN poke_champion.ruleset_context_mv rc
        ON rc.version_group_id = pm.version_group_id
),
name_rules AS (
    SELECT 10 AS prio, 'suffix_like'::text AS kind, '%-mega-x'::text AS pat, '超级{species}X'::text AS tmpl
    UNION ALL SELECT 20, 'suffix_like', '%-mega-y', '超级{species}Y'
    UNION ALL SELECT 30, 'suffix_like', '%-mega-z', '超级{species}Z'
    UNION ALL SELECT 31, 'suffix_like', '%-primal', '原始{species}'
    UNION ALL SELECT 32, 'suffix_like', '%-eternal', '永恒{species}'
    UNION ALL SELECT 40, 'suffix_like', '%-mega', '超级{species}'
    UNION ALL SELECT 41, 'suffix_like', '%-alola', '阿罗拉{species}'
    UNION ALL SELECT 50, 'suffix_like', '%-galar', '迦勒尔{species}'
    UNION ALL SELECT 60, 'suffix_like', '%-gmax', '超级巨{species}'
    UNION ALL SELECT 61, 'suffix_like', '%-hisui', '洗翠{species}'
    UNION ALL SELECT 70, 'identifier_eq', 'kyurem-black', '暗黑酋雷姆'
    UNION ALL SELECT 80, 'identifier_eq', 'kyurem-white', '焰白酋雷姆'
),
pokemon_names AS (
    SELECT
        p.id AS pokemon_id,
        COALESCE(
            direct_name.name,
            CASE
                WHEN rule.tmpl IS NULL THEN species_name.name
                ELSE replace(rule.tmpl, '{species}'::text, species_name.name)
            END,
            p.identifier
        ) AS localized_name
    FROM poke_raw.pokemon p
    JOIN poke_champion.ruleset_context_mv rc
        ON true
    LEFT JOIN poke_raw.pokemon_species_names direct_name
        ON direct_name.pokemon_species_id = p.id
       AND direct_name.local_language_id = rc.language_id
    LEFT JOIN poke_raw.pokemon_species_names species_name
        ON species_name.pokemon_species_id = p.species_id
       AND species_name.local_language_id = rc.language_id
    LEFT JOIN LATERAL (
        SELECT nr.tmpl
        FROM name_rules nr
        WHERE direct_name.name IS NULL
          AND (
              nr.kind = 'suffix_like' AND p.identifier LIKE nr.pat
              OR nr.kind = 'identifier_eq' AND p.identifier = nr.pat
          )
        ORDER BY nr.prio
        LIMIT 1
    ) rule ON true
),
stats AS (
    SELECT
        ps.pokemon_id,
        max(ps.base_stat) FILTER (WHERE ps.stat_id = 1) AS hp,
        max(ps.base_stat) FILTER (WHERE ps.stat_id = 2) AS attack,
        max(ps.base_stat) FILTER (WHERE ps.stat_id = 3) AS defense,
        max(ps.base_stat) FILTER (WHERE ps.stat_id = 4) AS special_attack,
        max(ps.base_stat) FILTER (WHERE ps.stat_id = 5) AS special_defense,
        max(ps.base_stat) FILTER (WHERE ps.stat_id = 6) AS speed
    FROM poke_raw.pokemon_stats ps
    WHERE ps.stat_id BETWEEN 1 AND 6
    GROUP BY ps.pokemon_id
),
types AS (
    SELECT
        cp.pokemon_id,
        COALESCE(past_type_1.type_id, current_type_1.type_id) AS type_1_id,
        COALESCE(past_type_2.type_id, current_type_2.type_id) AS type_2_id
    FROM champion_pokemon cp
    JOIN poke_champion.ruleset_context_mv rc
        ON true
    LEFT JOIN poke_raw.pokemon_types current_type_1
        ON current_type_1.pokemon_id = cp.pokemon_id
       AND current_type_1.slot = 1
    LEFT JOIN poke_raw.pokemon_types current_type_2
        ON current_type_2.pokemon_id = cp.pokemon_id
       AND current_type_2.slot = 2
    LEFT JOIN LATERAL (
        SELECT ppt.type_id
        FROM poke_raw.pokemon_types_past ppt
        WHERE ppt.pokemon_id = cp.pokemon_id
          AND ppt.slot = 1
          AND ppt.generation_id >= rc.generation_id
        ORDER BY ppt.generation_id
        LIMIT 1
    ) past_type_1 ON true
    LEFT JOIN LATERAL (
        SELECT ppt.type_id
        FROM poke_raw.pokemon_types_past ppt
        WHERE ppt.pokemon_id = cp.pokemon_id
          AND ppt.slot = 2
          AND ppt.generation_id >= rc.generation_id
        ORDER BY ppt.generation_id
        LIMIT 1
    ) past_type_2 ON true
),
ability_rows AS (
    SELECT
        pa.pokemon_id,
        CASE
            WHEN past_ability.ability_id IS NOT NULL THEN NULLIF(past_ability.ability_id, 0)
            ELSE pa.ability_id
        END AS ability_id
    FROM poke_raw.pokemon_abilities pa
    JOIN champion_pokemon cp
        ON cp.pokemon_id = pa.pokemon_id
    JOIN poke_champion.ruleset_context_mv rc
        ON true
    LEFT JOIN LATERAL (
        SELECT pap.ability_id
        FROM poke_raw.pokemon_abilities_past pap
        WHERE pap.pokemon_id = pa.pokemon_id
          AND pap.slot = pa.slot
          AND pap.is_hidden = pa.is_hidden
          AND pap.generation_id >= rc.generation_id
        ORDER BY pap.generation_id
        LIMIT 1
    ) past_ability ON true
),
abilities AS (
    SELECT
        ar.pokemon_id,
        COALESCE(
            array_agg(DISTINCT ar.ability_id ORDER BY ar.ability_id)
                FILTER (WHERE a.id IS NOT NULL),
            ARRAY[]::integer[]
        ) AS ability_ids,
        COALESCE(
            array_agg(DISTINCT a.identifier ORDER BY a.identifier)
                FILTER (WHERE a.id IS NOT NULL),
            ARRAY[]::text[]
        ) AS ability_identifiers,
        COALESCE(
            array_agg(DISTINCT an.name ORDER BY an.name)
                FILTER (WHERE a.id IS NOT NULL),
            ARRAY[]::text[]
        ) AS ability_names
    FROM ability_rows ar
    JOIN poke_champion.ruleset_context_mv rc
        ON true
    LEFT JOIN poke_raw.abilities a
        ON a.id = ar.ability_id
       AND a.is_main_series IS TRUE
    LEFT JOIN poke_raw.ability_names an
        ON an.ability_id = ar.ability_id
       AND an.local_language_id = rc.language_id
    GROUP BY ar.pokemon_id
),
default_forms AS (
    SELECT DISTINCT ON (pf.pokemon_id)
        pf.pokemon_id,
        pf.id AS form_id,
        pf.identifier AS form_identifier,
        pf.is_default,
        pf.is_battle_only,
        pf.is_mega
    FROM poke_raw.pokemon_forms pf
    ORDER BY pf.pokemon_id, pf.is_default DESC, pf.form_order, pf.id
)
SELECT
    rc.ruleset_id,
    rc.generation_id,
    rc.version_group_id,
    p.id AS pokemon_id,
    p.identifier AS pokemon_identifier,
    pn.localized_name AS pokemon_name,
    p.species_id,
    ps.identifier AS species_identifier,
    df.form_id,
    df.form_identifier,
    COALESCE(df.is_default, false) AS is_default_form,
    COALESCE(df.is_battle_only, false) AS is_battle_only_form,
    COALESCE(df.is_mega, false) AS is_mega_form,
    t.type_1_id,
    type_1.identifier AS type_1_identifier,
    type_1_name.name AS type_1_name,
    t.type_2_id,
    type_2.identifier AS type_2_identifier,
    type_2_name.name AS type_2_name,
    s.hp,
    s.attack,
    s.defense,
    s.special_attack,
    s.special_defense,
    s.speed,
    COALESCE(a.ability_ids, ARRAY[]::integer[]) AS ability_ids,
    COALESCE(a.ability_identifiers, ARRAY[]::text[]) AS ability_identifiers,
    COALESCE(a.ability_names, ARRAY[]::text[]) AS ability_names
FROM champion_pokemon cp
JOIN poke_champion.ruleset_context_mv rc
    ON true
JOIN poke_raw.pokemon p
    ON p.id = cp.pokemon_id
JOIN poke_raw.pokemon_species ps
    ON ps.id = p.species_id
LEFT JOIN pokemon_names pn
    ON pn.pokemon_id = p.id
LEFT JOIN default_forms df
    ON df.pokemon_id = p.id
LEFT JOIN stats s
    ON s.pokemon_id = p.id
LEFT JOIN types t
    ON t.pokemon_id = p.id
LEFT JOIN poke_raw.types type_1
    ON type_1.id = t.type_1_id
LEFT JOIN poke_raw.type_names type_1_name
    ON type_1_name.type_id = t.type_1_id
   AND type_1_name.local_language_id = rc.language_id
LEFT JOIN poke_raw.types type_2
    ON type_2.id = t.type_2_id
LEFT JOIN poke_raw.type_names type_2_name
    ON type_2_name.type_id = t.type_2_id
   AND type_2_name.local_language_id = rc.language_id
LEFT JOIN abilities a
    ON a.pokemon_id = p.id
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS pokemon_profile_mv_pk ON poke_champion.pokemon_profile_mv (pokemon_id);

CREATE INDEX IF NOT EXISTS pokemon_profile_mv_identifier_idx ON poke_champion.pokemon_profile_mv (pokemon_identifier);

CREATE INDEX IF NOT EXISTS pokemon_profile_mv_type_1_idx ON poke_champion.pokemon_profile_mv (type_1_id);

CREATE INDEX IF NOT EXISTS pokemon_profile_mv_type_2_idx ON poke_champion.pokemon_profile_mv (type_2_id);

CREATE INDEX IF NOT EXISTS pokemon_profile_mv_ability_ids_gin ON poke_champion.pokemon_profile_mv USING gin (ability_ids);

CREATE MATERIALIZED VIEW IF NOT EXISTS poke_champion.move_profile_mv AS
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
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS move_profile_mv_pk ON poke_champion.move_profile_mv (move_id);

CREATE INDEX IF NOT EXISTS move_profile_mv_identifier_idx ON poke_champion.move_profile_mv (move_identifier);

CREATE INDEX IF NOT EXISTS move_profile_mv_type_idx ON poke_champion.move_profile_mv (type_id);

CREATE INDEX IF NOT EXISTS move_profile_mv_damage_class_idx ON poke_champion.move_profile_mv (damage_class_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS poke_champion.type_efficacy_mv AS
SELECT
    rc.ruleset_id,
    rc.generation_id,
    te.damage_type_id,
    damage_type.identifier AS damage_type_identifier,
    damage_type_name.name AS damage_type_name,
    te.target_type_id,
    target_type.identifier AS target_type_identifier,
    target_type_name.name AS target_type_name,
    COALESCE(past.damage_factor, te.damage_factor) AS damage_factor
FROM poke_champion.ruleset_context_mv rc
JOIN poke_raw.type_efficacy te
    ON true
JOIN poke_raw.types damage_type
    ON damage_type.id = te.damage_type_id
   AND damage_type.generation_id <= rc.generation_id
   AND damage_type.id < 10000
JOIN poke_raw.types target_type
    ON target_type.id = te.target_type_id
   AND target_type.generation_id <= rc.generation_id
   AND target_type.id < 10000
LEFT JOIN LATERAL (
    SELECT tep.damage_factor
    FROM poke_raw.type_efficacy_past tep
    WHERE tep.damage_type_id = te.damage_type_id
      AND tep.target_type_id = te.target_type_id
      AND tep.generation_id >= rc.generation_id
    ORDER BY tep.generation_id
    LIMIT 1
) past ON true
LEFT JOIN poke_raw.type_names damage_type_name
    ON damage_type_name.type_id = te.damage_type_id
   AND damage_type_name.local_language_id = rc.language_id
LEFT JOIN poke_raw.type_names target_type_name
    ON target_type_name.type_id = te.target_type_id
   AND target_type_name.local_language_id = rc.language_id
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS type_efficacy_mv_pk ON poke_champion.type_efficacy_mv (damage_type_id, target_type_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS poke_champion.pokemon_learnset_mv AS
SELECT
    rc.ruleset_id,
    rc.generation_id,
    rc.version_group_id,
    pm.pokemon_id,
    pp.pokemon_identifier,
    pp.pokemon_name,
    pm.move_id,
    mp.move_identifier,
    mp.move_name,
    pm.pokemon_move_method_id,
    pmm.identifier AS move_method_identifier,
    pm.level,
    pm."order" AS learn_order,
    COALESCE(NULLIF(pm.mastery, ''), '') AS mastery,
    mp.type_id,
    mp.type_identifier,
    mp.type_name,
    mp.power,
    mp.pp,
    mp.accuracy,
    mp.priority,
    mp.damage_class_id,
    mp.damage_class_identifier
FROM poke_champion.ruleset_context_mv rc
JOIN poke_raw.pokemon_moves pm
    ON pm.version_group_id = rc.version_group_id
JOIN poke_champion.pokemon_profile_mv pp
    ON pp.pokemon_id = pm.pokemon_id
JOIN poke_champion.move_profile_mv mp
    ON mp.move_id = pm.move_id
LEFT JOIN poke_raw.pokemon_move_methods pmm
    ON pmm.id = pm.pokemon_move_method_id
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS pokemon_learnset_mv_pk ON poke_champion.pokemon_learnset_mv (pokemon_id, move_id, pokemon_move_method_id, level, learn_order, mastery);

CREATE INDEX IF NOT EXISTS pokemon_learnset_mv_pokemon_idx ON poke_champion.pokemon_learnset_mv (pokemon_id);

CREATE INDEX IF NOT EXISTS pokemon_learnset_mv_move_idx ON poke_champion.pokemon_learnset_mv (move_id);

CREATE INDEX IF NOT EXISTS pokemon_learnset_mv_method_idx ON poke_champion.pokemon_learnset_mv (move_method_identifier);

CREATE MATERIALIZED VIEW IF NOT EXISTS poke_champion.pokemon_catalog_zh_mv AS
SELECT
    pp.ruleset_id,
    pp.generation_id,
    pp.version_group_id,
    pp.pokemon_id,
    pp.pokemon_identifier,
    pp.pokemon_name,
    pp.type_1_name,
    pp.type_2_name,
    pp.hp,
    pp.attack,
    pp.defense,
    pp.special_attack,
    pp.special_defense,
    pp.speed,
    COALESCE(
        array_agg(DISTINCT pl.move_name ORDER BY pl.move_name)
            FILTER (WHERE pl.move_name IS NOT NULL),
        ARRAY[]::text[]
    ) AS move_names,
    pp.ability_names
FROM poke_champion.pokemon_profile_mv pp
LEFT JOIN poke_champion.pokemon_learnset_mv pl
    ON pl.pokemon_id = pp.pokemon_id
GROUP BY
    pp.ruleset_id,
    pp.generation_id,
    pp.version_group_id,
    pp.pokemon_id,
    pp.pokemon_identifier,
    pp.pokemon_name,
    pp.type_1_name,
    pp.type_2_name,
    pp.hp,
    pp.attack,
    pp.defense,
    pp.special_attack,
    pp.special_defense,
    pp.speed,
    pp.ability_names
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS pokemon_catalog_zh_mv_pk ON poke_champion.pokemon_catalog_zh_mv (pokemon_id);

CREATE INDEX IF NOT EXISTS pokemon_catalog_zh_mv_moves_gin ON poke_champion.pokemon_catalog_zh_mv USING gin (move_names);

CREATE INDEX IF NOT EXISTS pokemon_catalog_zh_mv_abilities_gin ON poke_champion.pokemon_catalog_zh_mv USING gin (ability_names);

CREATE MATERIALIZED VIEW IF NOT EXISTS poke_champion.pokemon_sprite_candidates_mv AS
WITH version_sprite_priority AS (
    SELECT
        25::integer AS version_group_id,
        'generation-ix'::text AS generation_identifier,
        'scarlet-violet'::text AS version_identifier,
        10::integer AS priority
),
desired_slots AS (
    SELECT 'front_default'::text AS sprite_slot
    UNION ALL SELECT 'back_default'::text
),
fallback_priority AS (
    SELECT 5::integer AS priority, 'pokemon'::text AS collection, NULL::text AS render_style
    UNION ALL SELECT 20, 'other', 'home'
    UNION ALL SELECT 30, 'other', 'official-artwork'
),
version_candidates AS (
    SELECT
        rc.ruleset_id,
        rc.generation_id,
        rc.version_group_id,
        asset.pokemon_id,
        asset.id AS asset_id,
        asset.relative_path,
        asset.sprite_slot,
        asset.is_front,
        asset.is_back,
        priority.priority,
        'version'::text AS selection_source,
        asset.collection,
        asset.render_style,
        asset.generation_identifier,
        asset.version_identifier,
        asset.mime_type,
        asset.sha256
    FROM poke_champion.ruleset_context_mv rc
    JOIN version_sprite_priority priority
        ON priority.version_group_id = rc.version_group_id
    JOIN desired_slots desired
        ON true
    JOIN poke_raw.sprite_assets asset
        ON asset.asset_category = 'pokemon'
       AND asset.pokemon_id IS NOT NULL
       AND asset.collection = 'versions'
       AND asset.generation_identifier = priority.generation_identifier
       AND asset.version_identifier = priority.version_identifier
       AND asset.sprite_slot = desired.sprite_slot
       AND asset.is_active IS TRUE
       AND asset.mime_type = 'image/png'
),
fallback_candidates AS (
    SELECT
        rc.ruleset_id,
        rc.generation_id,
        rc.version_group_id,
        asset.pokemon_id,
        asset.id AS asset_id,
        asset.relative_path,
        asset.sprite_slot,
        asset.is_front,
        asset.is_back,
        priority.priority,
        'fallback'::text AS selection_source,
        asset.collection,
        asset.render_style,
        asset.generation_identifier,
        asset.version_identifier,
        asset.mime_type,
        asset.sha256
    FROM poke_champion.ruleset_context_mv rc
    JOIN fallback_priority priority
        ON true
    JOIN desired_slots desired
        ON true
    JOIN poke_raw.sprite_assets asset
        ON asset.asset_category = 'pokemon'
       AND asset.pokemon_id IS NOT NULL
       AND asset.collection = priority.collection
       AND COALESCE(asset.render_style, '') = COALESCE(priority.render_style, '')
       AND asset.sprite_slot = desired.sprite_slot
       AND asset.is_active IS TRUE
       AND asset.mime_type = 'image/png'
       AND (
           priority.collection <> 'pokemon'
           OR (
               desired.sprite_slot = 'front_default'
               AND asset.relative_path = ('pokemon/' || asset.pokemon_id::text || '.png')
           )
           OR (
               desired.sprite_slot = 'back_default'
               AND asset.relative_path = ('pokemon/back/' || asset.pokemon_id::text || '.png')
           )
       )
)
SELECT *
FROM version_candidates
UNION ALL
SELECT *
FROM fallback_candidates
WITH DATA;

CREATE INDEX IF NOT EXISTS pokemon_sprite_candidates_mv_lookup_idx ON poke_champion.pokemon_sprite_candidates_mv (ruleset_id, version_group_id, pokemon_id, sprite_slot, priority);

CREATE INDEX IF NOT EXISTS pokemon_sprite_candidates_mv_asset_idx ON poke_champion.pokemon_sprite_candidates_mv (asset_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS poke_champion.pokemon_sprite_by_version_group_mv AS
WITH ranked AS (
    SELECT
        candidate.*,
        row_number() OVER (
            PARTITION BY
                candidate.ruleset_id,
                candidate.version_group_id,
                candidate.pokemon_id,
                candidate.sprite_slot
            ORDER BY
                candidate.priority,
                candidate.asset_id
        ) AS row_no
    FROM poke_champion.pokemon_sprite_candidates_mv candidate
)
SELECT
    ruleset_id,
    generation_id,
    version_group_id,
    pokemon_id,
    sprite_slot,
    is_front,
    is_back,
    asset_id,
    relative_path,
    priority,
    selection_source,
    collection,
    render_style,
    generation_identifier,
    version_identifier,
    mime_type,
    sha256
FROM ranked
WHERE row_no = 1
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS pokemon_sprite_by_version_group_mv_pk ON poke_champion.pokemon_sprite_by_version_group_mv (ruleset_id, version_group_id, pokemon_id, sprite_slot);

CREATE INDEX IF NOT EXISTS pokemon_sprite_by_version_group_mv_asset_idx ON poke_champion.pokemon_sprite_by_version_group_mv (asset_id);
