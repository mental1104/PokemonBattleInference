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

