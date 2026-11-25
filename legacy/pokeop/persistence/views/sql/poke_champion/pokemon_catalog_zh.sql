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

