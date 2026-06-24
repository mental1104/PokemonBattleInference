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

