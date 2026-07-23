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
