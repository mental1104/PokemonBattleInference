WITH version_sprite_priority AS (
    SELECT
        25::integer AS version_group_id,
        'generation-ix'::text AS generation_identifier,
        'scarlet-violet'::text AS version_identifier,
        10::integer AS priority
),
fallback_priority AS (
    SELECT 20::integer AS priority, 'other'::text AS collection, 'home'::text AS render_style
    UNION ALL SELECT 30, 'other', 'official-artwork'
    UNION ALL SELECT 40, 'pokemon', NULL
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
    JOIN poke_raw.sprite_assets asset
        ON asset.asset_category = 'pokemon'
       AND asset.pokemon_id IS NOT NULL
       AND asset.collection = 'versions'
       AND asset.generation_identifier = priority.generation_identifier
       AND asset.version_identifier = priority.version_identifier
       AND asset.sprite_slot = 'front_default'
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
    JOIN poke_raw.sprite_assets asset
        ON asset.asset_category = 'pokemon'
       AND asset.pokemon_id IS NOT NULL
       AND asset.collection = priority.collection
       AND COALESCE(asset.render_style, '') = COALESCE(priority.render_style, '')
       AND asset.sprite_slot = 'front_default'
       AND asset.is_active IS TRUE
       AND asset.mime_type = 'image/png'
       AND (
           priority.collection <> 'pokemon'
           OR asset.relative_path = ('pokemon/' || asset.pokemon_id::text || '.png')
       )
)
SELECT *
FROM version_candidates
UNION ALL
SELECT *
FROM fallback_candidates
