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
