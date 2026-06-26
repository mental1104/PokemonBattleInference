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

