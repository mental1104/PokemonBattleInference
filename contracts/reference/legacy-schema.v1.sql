-- Generated reference DDL only; do not execute as a migration.

CREATE TABLE poke_raw.abilities (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	generation_id INTEGER NOT NULL,
	is_main_series BOOLEAN NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.ability_changelog (
	id SERIAL NOT NULL,
	ability_id INTEGER NOT NULL,
	changed_in_version_group_id INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.ability_changelog_prose (
	ability_changelog_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	effect TEXT NOT NULL,
	PRIMARY KEY (ability_changelog_id, local_language_id, effect)
);

CREATE TABLE poke_raw.ability_flavor_text (
	ability_id INTEGER NOT NULL,
	version_group_id INTEGER NOT NULL,
	language_id INTEGER NOT NULL,
	flavor_text TEXT NOT NULL,
	PRIMARY KEY (ability_id, version_group_id, language_id, flavor_text)
);

CREATE TABLE poke_raw.ability_names (
	ability_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (ability_id, local_language_id, name)
);

CREATE TABLE poke_raw.ability_prose (
	ability_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	short_effect TEXT NOT NULL,
	effect TEXT NOT NULL,
	PRIMARY KEY (ability_id, local_language_id, short_effect, effect)
);

CREATE TABLE poke_raw.berries (
	id SERIAL NOT NULL,
	item_id INTEGER NOT NULL,
	firmness_id INTEGER NOT NULL,
	natural_gift_power INTEGER NOT NULL,
	natural_gift_type_id INTEGER NOT NULL,
	size INTEGER NOT NULL,
	max_harvest INTEGER NOT NULL,
	growth_time INTEGER NOT NULL,
	soil_dryness INTEGER NOT NULL,
	smoothness INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.berry_firmness (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.berry_firmness_names (
	berry_firmness_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (berry_firmness_id, local_language_id, name)
);

CREATE TABLE poke_raw.berry_flavors (
	berry_id INTEGER NOT NULL,
	contest_type_id INTEGER NOT NULL,
	flavor INTEGER NOT NULL,
	PRIMARY KEY (berry_id, contest_type_id, flavor)
);

CREATE TABLE poke_raw.characteristic_text (
	characteristic_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	message TEXT NOT NULL,
	PRIMARY KEY (characteristic_id, local_language_id, message)
);

CREATE TABLE poke_raw.characteristics (
	id SERIAL NOT NULL,
	stat_id INTEGER NOT NULL,
	gene_mod_5 INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.conquest_episode_names (
	episode_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (episode_id, local_language_id, name)
);

CREATE TABLE poke_raw.conquest_episode_warriors (
	episode_id INTEGER NOT NULL,
	warrior_id INTEGER NOT NULL,
	PRIMARY KEY (episode_id, warrior_id)
);

CREATE TABLE poke_raw.conquest_episodes (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.conquest_kingdom_names (
	kingdom_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (kingdom_id, local_language_id, name)
);

CREATE TABLE poke_raw.conquest_kingdoms (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	type_id INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.conquest_max_links (
	warrior_rank_id INTEGER NOT NULL,
	pokemon_species_id INTEGER NOT NULL,
	max_link INTEGER NOT NULL,
	PRIMARY KEY (warrior_rank_id, pokemon_species_id, max_link)
);

CREATE TABLE poke_raw.conquest_move_data (
	move_id INTEGER NOT NULL,
	power INTEGER NOT NULL,
	accuracy INTEGER NOT NULL,
	effect_chance INTEGER NOT NULL,
	effect_id INTEGER NOT NULL,
	range_id INTEGER NOT NULL,
	displacement_id INTEGER NOT NULL,
	PRIMARY KEY (move_id, power, accuracy, effect_chance, effect_id, range_id, displacement_id)
);

CREATE TABLE poke_raw.conquest_move_displacement_prose (
	move_displacement_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	short_effect TEXT NOT NULL,
	effect TEXT NOT NULL,
	PRIMARY KEY (move_displacement_id, local_language_id, name, short_effect, effect)
);

CREATE TABLE poke_raw.conquest_move_displacements (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	affects_target INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.conquest_move_effect_prose (
	conquest_move_effect_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	short_effect TEXT NOT NULL,
	effect TEXT NOT NULL,
	PRIMARY KEY (conquest_move_effect_id, local_language_id, short_effect, effect)
);

CREATE TABLE poke_raw.conquest_move_effects (
	id SERIAL NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.conquest_move_range_prose (
	conquest_move_range_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	description TEXT NOT NULL,
	PRIMARY KEY (conquest_move_range_id, local_language_id, name, description)
);

CREATE TABLE poke_raw.conquest_move_ranges (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	targets INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.conquest_pokemon_abilities (
	pokemon_species_id INTEGER NOT NULL,
	slot INTEGER NOT NULL,
	ability_id INTEGER NOT NULL,
	PRIMARY KEY (pokemon_species_id, slot, ability_id)
);

CREATE TABLE poke_raw.conquest_pokemon_evolution (
	evolved_species_id INTEGER NOT NULL,
	required_stat_id INTEGER NOT NULL,
	minimum_stat INTEGER NOT NULL,
	minimum_link INTEGER NOT NULL,
	kingdom_id INTEGER NOT NULL,
	warrior_gender_id INTEGER NOT NULL,
	item_id INTEGER NOT NULL,
	recruiting_ko_required INTEGER NOT NULL,
	PRIMARY KEY (evolved_species_id, required_stat_id, minimum_stat, minimum_link, kingdom_id, warrior_gender_id, item_id, recruiting_ko_required)
);

CREATE TABLE poke_raw.conquest_pokemon_moves (
	pokemon_species_id INTEGER NOT NULL,
	move_id INTEGER NOT NULL,
	PRIMARY KEY (pokemon_species_id, move_id)
);

CREATE TABLE poke_raw.conquest_pokemon_stats (
	pokemon_species_id INTEGER NOT NULL,
	conquest_stat_id INTEGER NOT NULL,
	base_stat INTEGER NOT NULL,
	PRIMARY KEY (pokemon_species_id, conquest_stat_id, base_stat)
);

CREATE TABLE poke_raw.conquest_stat_names (
	conquest_stat_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (conquest_stat_id, local_language_id, name)
);

CREATE TABLE poke_raw.conquest_stats (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	is_base BOOLEAN NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.conquest_transformation_pokemon (
	transformation_id INTEGER NOT NULL,
	pokemon_species_id INTEGER NOT NULL,
	PRIMARY KEY (transformation_id, pokemon_species_id)
);

CREATE TABLE poke_raw.conquest_transformation_warriors (
	transformation_id INTEGER NOT NULL,
	present_warrior_id INTEGER NOT NULL,
	PRIMARY KEY (transformation_id, present_warrior_id)
);

CREATE TABLE poke_raw.conquest_warrior_archetypes (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.conquest_warrior_names (
	warrior_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (warrior_id, local_language_id, name)
);

CREATE TABLE poke_raw.conquest_warrior_rank_stat_map (
	warrior_rank_id INTEGER NOT NULL,
	warrior_stat_id INTEGER NOT NULL,
	base_stat INTEGER NOT NULL,
	PRIMARY KEY (warrior_rank_id, warrior_stat_id, base_stat)
);

CREATE TABLE poke_raw.conquest_warrior_ranks (
	id SERIAL NOT NULL,
	warrior_id INTEGER NOT NULL,
	rank INTEGER NOT NULL,
	skill_id INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.conquest_warrior_skill_names (
	skill_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (skill_id, local_language_id, name)
);

CREATE TABLE poke_raw.conquest_warrior_skills (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.conquest_warrior_specialties (
	warrior_id INTEGER NOT NULL,
	type_id INTEGER NOT NULL,
	slot INTEGER NOT NULL,
	PRIMARY KEY (warrior_id, type_id, slot)
);

CREATE TABLE poke_raw.conquest_warrior_stat_names (
	warrior_stat_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (warrior_stat_id, local_language_id, name)
);

CREATE TABLE poke_raw.conquest_warrior_stats (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.conquest_warrior_transformation (
	transformed_warrior_rank_id INTEGER NOT NULL,
	is_automatic BOOLEAN NOT NULL,
	required_link INTEGER NOT NULL,
	completed_episode_id INTEGER NOT NULL,
	current_episode_id INTEGER NOT NULL,
	distant_warrior_id INTEGER NOT NULL,
	female_warlord_count INTEGER NOT NULL,
	pokemon_count INTEGER NOT NULL,
	collection_type_id INTEGER NOT NULL,
	warrior_count INTEGER NOT NULL,
	PRIMARY KEY (transformed_warrior_rank_id, is_automatic, required_link, completed_episode_id, current_episode_id, distant_warrior_id, female_warlord_count, pokemon_count, collection_type_id, warrior_count)
);

CREATE TABLE poke_raw.conquest_warriors (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	gender_id INTEGER NOT NULL,
	archetype_id INTEGER,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.contest_combos (
	first_move_id INTEGER NOT NULL,
	second_move_id INTEGER NOT NULL,
	PRIMARY KEY (first_move_id, second_move_id)
);

CREATE TABLE poke_raw.contest_effect_prose (
	contest_effect_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	flavor_text TEXT NOT NULL,
	effect TEXT NOT NULL,
	PRIMARY KEY (contest_effect_id, local_language_id, flavor_text, effect)
);

CREATE TABLE poke_raw.contest_effects (
	id SERIAL NOT NULL,
	appeal INTEGER NOT NULL,
	jam INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.contest_type_names (
	contest_type_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	flavor TEXT NOT NULL,
	color TEXT NOT NULL,
	PRIMARY KEY (contest_type_id, local_language_id, name, flavor, color)
);

CREATE TABLE poke_raw.contest_types (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.egg_group_prose (
	egg_group_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (egg_group_id, local_language_id, name)
);

CREATE TABLE poke_raw.egg_groups (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.encounter_condition_prose (
	encounter_condition_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (encounter_condition_id, local_language_id, name)
);

CREATE TABLE poke_raw.encounter_condition_value_map (
	encounter_id INTEGER NOT NULL,
	encounter_condition_value_id INTEGER NOT NULL,
	PRIMARY KEY (encounter_id, encounter_condition_value_id)
);

CREATE TABLE poke_raw.encounter_condition_value_prose (
	encounter_condition_value_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (encounter_condition_value_id, local_language_id, name)
);

CREATE TABLE poke_raw.encounter_condition_values (
	id SERIAL NOT NULL,
	encounter_condition_id INTEGER NOT NULL,
	identifier TEXT NOT NULL,
	is_default BOOLEAN NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.encounter_conditions (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.encounter_method_prose (
	encounter_method_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (encounter_method_id, local_language_id, name)
);

CREATE TABLE poke_raw.encounter_methods (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	"order" INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.encounter_slots (
	id SERIAL NOT NULL,
	version_group_id INTEGER NOT NULL,
	encounter_method_id INTEGER NOT NULL,
	slot INTEGER,
	rarity INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.encounters (
	id SERIAL NOT NULL,
	version_id INTEGER NOT NULL,
	location_area_id INTEGER NOT NULL,
	encounter_slot_id INTEGER NOT NULL,
	pokemon_id INTEGER NOT NULL,
	min_level INTEGER NOT NULL,
	max_level INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.evolution_chains (
	id SERIAL NOT NULL,
	baby_trigger_item_id INTEGER,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.evolution_trigger_prose (
	evolution_trigger_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (evolution_trigger_id, local_language_id, name)
);

CREATE TABLE poke_raw.evolution_triggers (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.experience (
	growth_rate_id INTEGER NOT NULL,
	level INTEGER NOT NULL,
	experience INTEGER NOT NULL,
	PRIMARY KEY (growth_rate_id, level, experience)
);

CREATE TABLE poke_raw.genders (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.generation_names (
	generation_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (generation_id, local_language_id, name)
);

CREATE TABLE poke_raw.generations (
	id SERIAL NOT NULL,
	main_region_id INTEGER NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.growth_rate_prose (
	growth_rate_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (growth_rate_id, local_language_id, name)
);

CREATE TABLE poke_raw.growth_rates (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	formula TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.item_categories (
	id SERIAL NOT NULL,
	pocket_id INTEGER NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.item_category_prose (
	item_category_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (item_category_id, local_language_id, name)
);

CREATE TABLE poke_raw.item_flag_map (
	item_id INTEGER NOT NULL,
	item_flag_id INTEGER NOT NULL,
	PRIMARY KEY (item_id, item_flag_id)
);

CREATE TABLE poke_raw.item_flag_prose (
	item_flag_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	description TEXT NOT NULL,
	PRIMARY KEY (item_flag_id, local_language_id, name, description)
);

CREATE TABLE poke_raw.item_flags (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.item_flavor_summaries (
	item_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	flavor_summary TEXT NOT NULL,
	PRIMARY KEY (item_id, local_language_id, flavor_summary)
);

CREATE TABLE poke_raw.item_flavor_text (
	item_id INTEGER NOT NULL,
	version_group_id INTEGER NOT NULL,
	language_id INTEGER NOT NULL,
	flavor_text TEXT NOT NULL,
	PRIMARY KEY (item_id, version_group_id, language_id, flavor_text)
);

CREATE TABLE poke_raw.item_fling_effect_prose (
	item_fling_effect_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	effect TEXT NOT NULL,
	PRIMARY KEY (item_fling_effect_id, local_language_id, effect)
);

CREATE TABLE poke_raw.item_fling_effects (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.item_game_indices (
	item_id INTEGER NOT NULL,
	generation_id INTEGER NOT NULL,
	game_index INTEGER NOT NULL,
	PRIMARY KEY (item_id, generation_id, game_index)
);

CREATE TABLE poke_raw.item_names (
	item_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (item_id, local_language_id, name)
);

CREATE TABLE poke_raw.item_pocket_names (
	item_pocket_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (item_pocket_id, local_language_id, name)
);

CREATE TABLE poke_raw.item_pockets (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.item_prose (
	item_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	short_effect TEXT NOT NULL,
	effect TEXT NOT NULL,
	PRIMARY KEY (item_id, local_language_id, short_effect, effect)
);

CREATE TABLE poke_raw.items (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	category_id INTEGER NOT NULL,
	cost INTEGER NOT NULL,
	fling_power INTEGER,
	fling_effect_id INTEGER,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.language_names (
	language_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (language_id, local_language_id, name)
);

CREATE TABLE poke_raw.languages (
	id SERIAL NOT NULL,
	iso639 TEXT NOT NULL,
	iso3166 TEXT NOT NULL,
	identifier TEXT NOT NULL,
	official INTEGER NOT NULL,
	"order" INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.location_area_encounter_rates (
	location_area_id INTEGER NOT NULL,
	encounter_method_id INTEGER NOT NULL,
	version_id INTEGER NOT NULL,
	rate INTEGER NOT NULL,
	PRIMARY KEY (location_area_id, encounter_method_id, version_id, rate)
);

CREATE TABLE poke_raw.location_area_prose (
	location_area_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (location_area_id, local_language_id, name)
);

CREATE TABLE poke_raw.location_areas (
	id SERIAL NOT NULL,
	location_id INTEGER NOT NULL,
	game_index INTEGER NOT NULL,
	identifier TEXT,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.location_game_indices (
	location_id INTEGER NOT NULL,
	generation_id INTEGER NOT NULL,
	game_index INTEGER NOT NULL,
	PRIMARY KEY (location_id, generation_id, game_index)
);

CREATE TABLE poke_raw.location_names (
	location_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	subtitle TEXT NOT NULL,
	PRIMARY KEY (location_id, local_language_id, name, subtitle)
);

CREATE TABLE poke_raw.locations (
	id SERIAL NOT NULL,
	region_id INTEGER,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.machines (
	machine_number INTEGER NOT NULL,
	version_group_id INTEGER NOT NULL,
	item_id INTEGER NOT NULL,
	move_id INTEGER NOT NULL,
	PRIMARY KEY (machine_number, version_group_id, item_id, move_id)
);

CREATE TABLE poke_raw.move_battle_style_prose (
	move_battle_style_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (move_battle_style_id, local_language_id, name)
);

CREATE TABLE poke_raw.move_battle_styles (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.move_changelog (
	move_id INTEGER NOT NULL,
	changed_in_version_group_id INTEGER NOT NULL,
	type_id INTEGER NOT NULL,
	power INTEGER NOT NULL,
	pp INTEGER NOT NULL,
	accuracy INTEGER NOT NULL,
	priority TEXT NOT NULL,
	target_id INTEGER NOT NULL,
	effect_id INTEGER NOT NULL,
	effect_chance INTEGER NOT NULL,
	PRIMARY KEY (move_id, changed_in_version_group_id, type_id, power, pp, accuracy, priority, target_id, effect_id, effect_chance)
);

CREATE TABLE poke_raw.move_damage_class_prose (
	move_damage_class_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	description TEXT NOT NULL,
	PRIMARY KEY (move_damage_class_id, local_language_id, name, description)
);

CREATE TABLE poke_raw.move_damage_classes (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.move_effect_changelog (
	id SERIAL NOT NULL,
	effect_id INTEGER NOT NULL,
	changed_in_version_group_id INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.move_effect_changelog_prose (
	move_effect_changelog_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	effect TEXT NOT NULL,
	PRIMARY KEY (move_effect_changelog_id, local_language_id, effect)
);

CREATE TABLE poke_raw.move_effect_prose (
	move_effect_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	short_effect TEXT NOT NULL,
	effect TEXT NOT NULL,
	PRIMARY KEY (move_effect_id, local_language_id, short_effect, effect)
);

CREATE TABLE poke_raw.move_effects (
	id SERIAL NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.move_flag_map (
	move_id INTEGER NOT NULL,
	move_flag_id INTEGER NOT NULL,
	PRIMARY KEY (move_id, move_flag_id)
);

CREATE TABLE poke_raw.move_flag_prose (
	move_flag_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	description TEXT NOT NULL,
	PRIMARY KEY (move_flag_id, local_language_id, name, description)
);

CREATE TABLE poke_raw.move_flags (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.move_flavor_summaries (
	move_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	flavor_summary TEXT NOT NULL,
	PRIMARY KEY (move_id, local_language_id, flavor_summary)
);

CREATE TABLE poke_raw.move_flavor_text (
	move_id INTEGER NOT NULL,
	version_group_id INTEGER NOT NULL,
	language_id INTEGER NOT NULL,
	flavor_text TEXT NOT NULL,
	PRIMARY KEY (move_id, version_group_id, language_id, flavor_text)
);

CREATE TABLE poke_raw.move_meta (
	move_id INTEGER NOT NULL,
	meta_category_id INTEGER NOT NULL,
	meta_ailment_id INTEGER NOT NULL,
	min_hits INTEGER NOT NULL,
	max_hits INTEGER NOT NULL,
	min_turns INTEGER NOT NULL,
	max_turns INTEGER NOT NULL,
	drain TEXT NOT NULL,
	healing TEXT NOT NULL,
	crit_rate INTEGER NOT NULL,
	ailment_chance INTEGER NOT NULL,
	flinch_chance INTEGER NOT NULL,
	stat_chance INTEGER NOT NULL,
	PRIMARY KEY (move_id, meta_category_id, meta_ailment_id, min_hits, max_hits, min_turns, max_turns, drain, healing, crit_rate, ailment_chance, flinch_chance, stat_chance)
);

CREATE TABLE poke_raw.move_meta_ailment_names (
	move_meta_ailment_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (move_meta_ailment_id, local_language_id, name)
);

CREATE TABLE poke_raw.move_meta_ailments (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.move_meta_categories (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.move_meta_category_prose (
	move_meta_category_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	description TEXT NOT NULL,
	PRIMARY KEY (move_meta_category_id, local_language_id, description)
);

CREATE TABLE poke_raw.move_meta_stat_changes (
	move_id INTEGER NOT NULL,
	stat_id INTEGER NOT NULL,
	change TEXT NOT NULL,
	PRIMARY KEY (move_id, stat_id, change)
);

CREATE TABLE poke_raw.move_names (
	move_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (move_id, local_language_id, name)
);

CREATE TABLE poke_raw.move_target_prose (
	move_target_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	description TEXT NOT NULL,
	PRIMARY KEY (move_target_id, local_language_id, name, description)
);

CREATE TABLE poke_raw.move_targets (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.moves (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	generation_id INTEGER NOT NULL,
	type_id INTEGER NOT NULL,
	power INTEGER,
	pp INTEGER NOT NULL,
	accuracy INTEGER,
	priority TEXT NOT NULL,
	target_id INTEGER NOT NULL,
	damage_class_id INTEGER NOT NULL,
	effect_id INTEGER NOT NULL,
	effect_chance INTEGER,
	contest_type_id INTEGER NOT NULL,
	contest_effect_id INTEGER NOT NULL,
	super_contest_effect_id INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.nature_battle_style_preferences (
	nature_id INTEGER NOT NULL,
	move_battle_style_id INTEGER NOT NULL,
	low_hp_preference INTEGER NOT NULL,
	high_hp_preference INTEGER NOT NULL,
	PRIMARY KEY (nature_id, move_battle_style_id, low_hp_preference, high_hp_preference)
);

CREATE TABLE poke_raw.nature_names (
	nature_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (nature_id, local_language_id, name)
);

CREATE TABLE poke_raw.nature_pokeathlon_stats (
	nature_id INTEGER NOT NULL,
	pokeathlon_stat_id INTEGER NOT NULL,
	max_change TEXT NOT NULL,
	PRIMARY KEY (nature_id, pokeathlon_stat_id, max_change)
);

CREATE TABLE poke_raw.natures (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	decreased_stat_id INTEGER NOT NULL,
	increased_stat_id INTEGER NOT NULL,
	hates_flavor_id INTEGER NOT NULL,
	likes_flavor_id INTEGER NOT NULL,
	game_index INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pal_park (
	species_id INTEGER NOT NULL,
	area_id INTEGER NOT NULL,
	base_score INTEGER NOT NULL,
	rate INTEGER NOT NULL,
	PRIMARY KEY (species_id, area_id, base_score, rate)
);

CREATE TABLE poke_raw.pal_park_area_names (
	pal_park_area_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (pal_park_area_id, local_language_id, name)
);

CREATE TABLE poke_raw.pal_park_areas (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pokeathlon_stat_names (
	pokeathlon_stat_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (pokeathlon_stat_id, local_language_id, name)
);

CREATE TABLE poke_raw.pokeathlon_stats (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pokedex_prose (
	pokedex_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	description TEXT NOT NULL,
	PRIMARY KEY (pokedex_id, local_language_id, name, description)
);

CREATE TABLE poke_raw.pokedex_version_groups (
	pokedex_id INTEGER NOT NULL,
	version_group_id INTEGER NOT NULL,
	PRIMARY KEY (pokedex_id, version_group_id)
);

CREATE TABLE poke_raw.pokedexes (
	id SERIAL NOT NULL,
	region_id INTEGER,
	identifier TEXT NOT NULL,
	is_main_series BOOLEAN NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pokemon (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	species_id INTEGER NOT NULL,
	height INTEGER NOT NULL,
	weight INTEGER NOT NULL,
	base_experience INTEGER NOT NULL,
	"order" INTEGER NOT NULL,
	is_default BOOLEAN NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pokemon_abilities (
	pokemon_id INTEGER NOT NULL,
	ability_id INTEGER NOT NULL,
	is_hidden BOOLEAN NOT NULL,
	slot INTEGER NOT NULL,
	PRIMARY KEY (pokemon_id, ability_id, is_hidden, slot)
);

CREATE TABLE poke_raw.pokemon_abilities_past (
	pokemon_id INTEGER NOT NULL,
	generation_id INTEGER NOT NULL,
	ability_id INTEGER NOT NULL,
	is_hidden BOOLEAN NOT NULL,
	slot INTEGER NOT NULL,
	PRIMARY KEY (pokemon_id, generation_id, ability_id, is_hidden, slot)
);

CREATE TABLE poke_raw.pokemon_color_names (
	pokemon_color_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (pokemon_color_id, local_language_id, name)
);

CREATE TABLE poke_raw.pokemon_colors (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pokemon_dex_numbers (
	"﻿species_id" INTEGER NOT NULL,
	pokedex_id INTEGER NOT NULL,
	pokedex_number INTEGER NOT NULL,
	PRIMARY KEY ("﻿species_id", pokedex_id, pokedex_number)
);

CREATE TABLE poke_raw.pokemon_egg_groups (
	species_id INTEGER NOT NULL,
	egg_group_id INTEGER NOT NULL,
	PRIMARY KEY (species_id, egg_group_id)
);

CREATE TABLE poke_raw.pokemon_evolution (
	id SERIAL NOT NULL,
	evolved_species_id INTEGER NOT NULL,
	evolution_trigger_id INTEGER NOT NULL,
	trigger_item_id INTEGER,
	minimum_level INTEGER,
	gender_id INTEGER,
	location_id INTEGER,
	held_item_id INTEGER,
	time_of_day TEXT,
	known_move_id INTEGER,
	known_move_type_id INTEGER,
	minimum_happiness INTEGER,
	minimum_beauty INTEGER,
	minimum_affection TEXT,
	relative_physical_stats TEXT,
	party_species_id INTEGER,
	party_type_id INTEGER,
	trade_species_id INTEGER,
	needs_overworld_rain INTEGER NOT NULL,
	turn_upside_down INTEGER NOT NULL,
	region_id INTEGER,
	base_form_id INTEGER,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pokemon_form_generations (
	pokemon_form_id INTEGER NOT NULL,
	generation_id INTEGER NOT NULL,
	game_index INTEGER NOT NULL,
	PRIMARY KEY (pokemon_form_id, generation_id, game_index)
);

CREATE TABLE poke_raw.pokemon_form_names (
	pokemon_form_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	form_name TEXT NOT NULL,
	pokemon_name TEXT NOT NULL,
	PRIMARY KEY (pokemon_form_id, local_language_id, form_name, pokemon_name)
);

CREATE TABLE poke_raw.pokemon_form_pokeathlon_stats (
	pokemon_form_id INTEGER NOT NULL,
	pokeathlon_stat_id INTEGER NOT NULL,
	minimum_stat INTEGER NOT NULL,
	base_stat INTEGER NOT NULL,
	maximum_stat INTEGER NOT NULL,
	PRIMARY KEY (pokemon_form_id, pokeathlon_stat_id, minimum_stat, base_stat, maximum_stat)
);

CREATE TABLE poke_raw.pokemon_form_types (
	pokemon_form_id INTEGER NOT NULL,
	type_id INTEGER NOT NULL,
	slot INTEGER NOT NULL,
	PRIMARY KEY (pokemon_form_id, type_id, slot)
);

CREATE TABLE poke_raw.pokemon_forms (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	form_identifier TEXT,
	pokemon_id INTEGER NOT NULL,
	introduced_in_version_group_id INTEGER NOT NULL,
	is_default BOOLEAN NOT NULL,
	is_battle_only BOOLEAN NOT NULL,
	is_mega BOOLEAN NOT NULL,
	form_order INTEGER NOT NULL,
	"order" INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pokemon_game_indices (
	pokemon_id INTEGER NOT NULL,
	version_id INTEGER NOT NULL,
	game_index INTEGER NOT NULL,
	PRIMARY KEY (pokemon_id, version_id, game_index)
);

CREATE TABLE poke_raw.pokemon_habitat_names (
	pokemon_habitat_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (pokemon_habitat_id, local_language_id, name)
);

CREATE TABLE poke_raw.pokemon_habitats (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pokemon_items (
	pokemon_id INTEGER NOT NULL,
	version_id INTEGER NOT NULL,
	item_id INTEGER NOT NULL,
	rarity INTEGER NOT NULL,
	PRIMARY KEY (pokemon_id, version_id, item_id, rarity)
);

CREATE TABLE poke_raw.pokemon_move_method_prose (
	pokemon_move_method_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	description TEXT NOT NULL,
	PRIMARY KEY (pokemon_move_method_id, local_language_id, name, description)
);

CREATE TABLE poke_raw.pokemon_move_methods (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pokemon_moves (
	pokemon_id INTEGER NOT NULL,
	version_group_id INTEGER NOT NULL,
	move_id INTEGER NOT NULL,
	pokemon_move_method_id INTEGER NOT NULL,
	level INTEGER NOT NULL,
	"order" INTEGER NOT NULL,
	mastery TEXT NOT NULL,
	PRIMARY KEY (pokemon_id, version_group_id, move_id, pokemon_move_method_id, level, "order", mastery)
);

CREATE TABLE poke_raw.pokemon_shape_prose (
	pokemon_shape_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	awesome_name TEXT NOT NULL,
	description TEXT NOT NULL,
	PRIMARY KEY (pokemon_shape_id, local_language_id, name, awesome_name, description)
);

CREATE TABLE poke_raw.pokemon_shapes (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pokemon_species (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	generation_id INTEGER NOT NULL,
	evolves_from_species_id INTEGER,
	evolution_chain_id INTEGER NOT NULL,
	color_id INTEGER NOT NULL,
	shape_id INTEGER NOT NULL,
	habitat_id INTEGER NOT NULL,
	gender_rate TEXT NOT NULL,
	capture_rate INTEGER NOT NULL,
	base_happiness INTEGER NOT NULL,
	is_baby BOOLEAN NOT NULL,
	hatch_counter INTEGER NOT NULL,
	has_gender_differences BOOLEAN NOT NULL,
	growth_rate_id INTEGER NOT NULL,
	forms_switchable INTEGER NOT NULL,
	is_legendary BOOLEAN NOT NULL,
	is_mythical BOOLEAN NOT NULL,
	"order" INTEGER NOT NULL,
	conquest_order INTEGER,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.pokemon_species_flavor_summaries (
	pokemon_species_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	flavor_summary TEXT NOT NULL,
	PRIMARY KEY (pokemon_species_id, local_language_id, flavor_summary)
);

CREATE TABLE poke_raw.pokemon_species_flavor_text (
	species_id INTEGER NOT NULL,
	version_id INTEGER NOT NULL,
	language_id INTEGER NOT NULL,
	flavor_text TEXT NOT NULL,
	PRIMARY KEY (species_id, version_id, language_id, flavor_text)
);

CREATE TABLE poke_raw.pokemon_species_names (
	pokemon_species_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	genus TEXT NOT NULL,
	PRIMARY KEY (pokemon_species_id, local_language_id, name, genus)
);

CREATE TABLE poke_raw.pokemon_species_prose (
	pokemon_species_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	form_description TEXT NOT NULL,
	PRIMARY KEY (pokemon_species_id, local_language_id, form_description)
);

CREATE TABLE poke_raw.pokemon_stats (
	pokemon_id INTEGER NOT NULL,
	stat_id INTEGER NOT NULL,
	base_stat INTEGER NOT NULL,
	effort INTEGER NOT NULL,
	PRIMARY KEY (pokemon_id, stat_id, base_stat, effort)
);

CREATE TABLE poke_raw.pokemon_types (
	pokemon_id INTEGER NOT NULL,
	type_id INTEGER NOT NULL,
	slot INTEGER NOT NULL,
	PRIMARY KEY (pokemon_id, type_id, slot)
);

CREATE TABLE poke_raw.pokemon_types_past (
	pokemon_id INTEGER NOT NULL,
	generation_id INTEGER NOT NULL,
	type_id INTEGER NOT NULL,
	slot INTEGER NOT NULL,
	PRIMARY KEY (pokemon_id, generation_id, type_id, slot)
);

CREATE TABLE poke_raw.region_names (
	region_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (region_id, local_language_id, name)
);

CREATE TABLE poke_raw.regions (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.sprite_import_batches (
	id SERIAL NOT NULL,
	manifest_hash TEXT NOT NULL,
	source_commit TEXT,
	status TEXT NOT NULL,
	files_seen INTEGER NOT NULL,
	imported_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.stat_names (
	stat_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (stat_id, local_language_id, name)
);

CREATE TABLE poke_raw.stats (
	id SERIAL NOT NULL,
	damage_class_id INTEGER,
	identifier TEXT NOT NULL,
	is_battle_only BOOLEAN NOT NULL,
	game_index INTEGER,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.super_contest_combos (
	first_move_id INTEGER NOT NULL,
	second_move_id INTEGER NOT NULL,
	PRIMARY KEY (first_move_id, second_move_id)
);

CREATE TABLE poke_raw.super_contest_effect_prose (
	super_contest_effect_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	flavor_text TEXT NOT NULL,
	PRIMARY KEY (super_contest_effect_id, local_language_id, flavor_text)
);

CREATE TABLE poke_raw.super_contest_effects (
	id SERIAL NOT NULL,
	appeal INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.translations_cs (
	language_id INTEGER NOT NULL,
	"table" TEXT NOT NULL,
	id SERIAL NOT NULL,
	"column" TEXT NOT NULL,
	source_crc TEXT NOT NULL,
	string TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.type_efficacy (
	damage_type_id INTEGER NOT NULL,
	target_type_id INTEGER NOT NULL,
	damage_factor INTEGER NOT NULL,
	PRIMARY KEY (damage_type_id, target_type_id, damage_factor)
);

CREATE TABLE poke_raw.type_efficacy_past (
	damage_type_id INTEGER NOT NULL,
	target_type_id INTEGER NOT NULL,
	damage_factor INTEGER NOT NULL,
	generation_id INTEGER NOT NULL,
	PRIMARY KEY (damage_type_id, target_type_id, damage_factor, generation_id)
);

CREATE TABLE poke_raw.type_game_indices (
	type_id INTEGER NOT NULL,
	generation_id INTEGER NOT NULL,
	game_index INTEGER NOT NULL,
	PRIMARY KEY (type_id, generation_id, game_index)
);

CREATE TABLE poke_raw.type_names (
	type_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (type_id, local_language_id, name)
);

CREATE TABLE poke_raw.types (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	generation_id INTEGER NOT NULL,
	damage_class_id INTEGER,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.version_group_pokemon_move_methods (
	version_group_id INTEGER NOT NULL,
	pokemon_move_method_id INTEGER NOT NULL,
	PRIMARY KEY (version_group_id, pokemon_move_method_id)
);

CREATE TABLE poke_raw.version_group_regions (
	version_group_id INTEGER NOT NULL,
	region_id INTEGER NOT NULL,
	PRIMARY KEY (version_group_id, region_id)
);

CREATE TABLE poke_raw.version_groups (
	id SERIAL NOT NULL,
	identifier TEXT NOT NULL,
	generation_id INTEGER NOT NULL,
	"order" INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.version_names (
	version_id INTEGER NOT NULL,
	local_language_id INTEGER NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (version_id, local_language_id, name)
);

CREATE TABLE poke_raw.versions (
	id SERIAL NOT NULL,
	version_group_id INTEGER NOT NULL,
	identifier TEXT NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE poke_raw.sprite_assets (
	id SERIAL NOT NULL,
	relative_path TEXT NOT NULL,
	asset_category TEXT NOT NULL,
	pokemon_id INTEGER,
	generation_identifier TEXT,
	version_identifier TEXT,
	collection TEXT,
	render_style TEXT,
	sprite_slot TEXT,
	is_front BOOLEAN,
	is_back BOOLEAN,
	is_female BOOLEAN,
	is_shiny BOOLEAN,
	is_animated BOOLEAN,
	parse_status TEXT NOT NULL,
	mime_type TEXT NOT NULL,
	byte_size BIGINT NOT NULL,
	sha256 TEXT NOT NULL,
	content BYTEA NOT NULL,
	first_seen_batch_id INTEGER NOT NULL,
	last_seen_batch_id INTEGER NOT NULL,
	imported_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	is_active BOOLEAN NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT sprite_assets_relative_path_uq UNIQUE (relative_path),
	FOREIGN KEY(first_seen_batch_id) REFERENCES poke_raw.sprite_import_batches (id),
	FOREIGN KEY(last_seen_batch_id) REFERENCES poke_raw.sprite_import_batches (id)
);

CREATE TABLE poke_runtime.battle_inference_jobs (
	job_id TEXT NOT NULL,
	ruleset_id TEXT NOT NULL,
	version_group_id INTEGER NOT NULL,
	calculation_revision TEXT NOT NULL,
	status VARCHAR(40) NOT NULL,
	attempt_count INTEGER NOT NULL,
	lease_owner TEXT,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	heartbeat_at TIMESTAMP WITH TIME ZONE,
	cancel_requested_at TIMESTAMP WITH TIME ZONE,
	last_failure_code VARCHAR(64),
	last_failure_diagnostic TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (job_id),
	CONSTRAINT battle_inference_jobs_status_ck CHECK (status IN ('pending', 'preparing', 'running', 'succeeded', 'completed_with_failures', 'cancel_requested', 'cancelled', 'failed')),
	CONSTRAINT battle_inference_jobs_attempt_count_ck CHECK (attempt_count >= 0),
	CONSTRAINT battle_inference_jobs_lease_ck CHECK ((lease_owner IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL) OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL))
);

CREATE INDEX battle_inference_jobs_claim_idx ON poke_runtime.battle_inference_jobs (status, lease_expires_at, created_at);

CREATE TABLE poke_runtime.stat_configuration_preferences (
	id SERIAL NOT NULL,
	tenant_id TEXT NOT NULL,
	role VARCHAR(16) NOT NULL,
	reference_type VARCHAR(16) NOT NULL,
	reference_key TEXT NOT NULL,
	sort_order INTEGER NOT NULL,
	hidden BOOLEAN NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT stat_configuration_preferences_ref_uq UNIQUE (tenant_id, role, reference_type, reference_key),
	CONSTRAINT stat_configuration_preferences_role_ck CHECK (role IN ('attacker', 'defender')),
	CONSTRAINT stat_configuration_preferences_ref_type_ck CHECK (reference_type IN ('builtin', 'custom')),
	CONSTRAINT stat_configuration_preferences_sort_ck CHECK (sort_order >= 0)
);

CREATE INDEX stat_configuration_preferences_tenant_role_idx ON poke_runtime.stat_configuration_preferences (tenant_id, role, sort_order);

CREATE TABLE poke_runtime.stat_configurations (
	id TEXT NOT NULL,
	tenant_id TEXT NOT NULL,
	name VARCHAR(48) NOT NULL,
	nature_id VARCHAR(32) NOT NULL,
	role VARCHAR(16) NOT NULL,
	binding_kind VARCHAR(16) NOT NULL,
	pokemon_id INTEGER,
	ev_hp INTEGER NOT NULL,
	ev_attack INTEGER NOT NULL,
	ev_defense INTEGER NOT NULL,
	ev_special_attack INTEGER NOT NULL,
	ev_special_defense INTEGER NOT NULL,
	ev_speed INTEGER NOT NULL,
	iv_hp INTEGER NOT NULL,
	iv_attack INTEGER NOT NULL,
	iv_defense INTEGER NOT NULL,
	iv_special_attack INTEGER NOT NULL,
	iv_special_defense INTEGER NOT NULL,
	iv_speed INTEGER NOT NULL,
	is_deleted BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT stat_configurations_name_len_ck CHECK (char_length(name) BETWEEN 1 AND 48),
	CONSTRAINT stat_configurations_role_ck CHECK (role IN ('attacker', 'defender', 'both')),
	CONSTRAINT stat_configurations_binding_kind_ck CHECK (binding_kind IN ('global', 'pokemon')),
	CONSTRAINT stat_configurations_binding_ck CHECK ((binding_kind = 'global' AND pokemon_id IS NULL) OR (binding_kind = 'pokemon' AND pokemon_id IS NOT NULL AND pokemon_id > 0)),
	CONSTRAINT stat_configurations_ev_each_ck CHECK (ev_hp BETWEEN 0 AND 252 AND ev_attack BETWEEN 0 AND 252 AND ev_defense BETWEEN 0 AND 252 AND ev_special_attack BETWEEN 0 AND 252 AND ev_special_defense BETWEEN 0 AND 252 AND ev_speed BETWEEN 0 AND 252),
	CONSTRAINT stat_configurations_ev_total_ck CHECK (ev_hp + ev_attack + ev_defense + ev_special_attack + ev_special_defense + ev_speed <= 510),
	CONSTRAINT stat_configurations_iv_each_ck CHECK (iv_hp BETWEEN 0 AND 31 AND iv_attack BETWEEN 0 AND 31 AND iv_defense BETWEEN 0 AND 31 AND iv_special_attack BETWEEN 0 AND 31 AND iv_special_defense BETWEEN 0 AND 31 AND iv_speed BETWEEN 0 AND 31)
);

CREATE INDEX stat_configurations_tenant_pokemon_idx ON poke_runtime.stat_configurations (tenant_id, binding_kind, pokemon_id);

CREATE INDEX stat_configurations_tenant_role_idx ON poke_runtime.stat_configurations (tenant_id, role, is_deleted);

CREATE TABLE poke_runtime.battle_inference_cases (
	id BIGSERIAL NOT NULL,
	job_id TEXT NOT NULL,
	sequence_no INTEGER NOT NULL,
	configuration_pair_id TEXT NOT NULL,
	attacker_configuration_id TEXT NOT NULL,
	defender_configuration_id TEXT NOT NULL,
	attacker_move_ids INTEGER[] NOT NULL,
	defender_move_ids INTEGER[] NOT NULL,
	status VARCHAR(40) NOT NULL,
	attempt_count INTEGER NOT NULL,
	lease_owner TEXT,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	heartbeat_at TIMESTAMP WITH TIME ZONE,
	attacker_win_numerator TEXT,
	attacker_win_denominator TEXT,
	defender_win_numerator TEXT,
	defender_win_denominator TEXT,
	draw_numerator TEXT,
	draw_denominator TEXT,
	expected_turns_kind VARCHAR(32),
	expected_turns_numerator TEXT,
	expected_turns_denominator TEXT,
	node_count BIGINT NOT NULL,
	edge_count BIGINT NOT NULL,
	progress_phase VARCHAR(64),
	observed_node_count BIGINT NOT NULL,
	observed_edge_count BIGINT NOT NULL,
	expanded_node_count BIGINT NOT NULL,
	frontier_count BIGINT NOT NULL,
	action_pair_completed_count BIGINT NOT NULL,
	action_pair_total_count BIGINT NOT NULL,
	budget_consumed BIGINT NOT NULL,
	explanation_json TEXT,
	failure_code VARCHAR(64),
	diagnostic TEXT,
	last_failure_code VARCHAR(64),
	last_failure_diagnostic TEXT,
	result_fingerprint VARCHAR(64),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT battle_inference_cases_job_pair_uq UNIQUE (job_id, configuration_pair_id),
	CONSTRAINT battle_inference_cases_job_sequence_uq UNIQUE (job_id, sequence_no),
	CONSTRAINT battle_inference_cases_sequence_ck CHECK (sequence_no >= 0),
	CONSTRAINT battle_inference_cases_status_ck CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'truncated', 'cancelled')),
	CONSTRAINT battle_inference_cases_nonnegative_ck CHECK (attempt_count >= 0 AND node_count >= 0 AND edge_count >= 0 AND observed_node_count >= 0 AND observed_edge_count >= 0 AND expanded_node_count >= 0 AND frontier_count >= 0 AND action_pair_completed_count >= 0 AND action_pair_total_count >= 0 AND action_pair_completed_count <= action_pair_total_count AND budget_consumed >= 0),
	CONSTRAINT battle_inference_cases_lease_ck CHECK ((lease_owner IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL) OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL)),
	CONSTRAINT battle_inference_cases_expected_turns_kind_ck CHECK (expected_turns_kind IS NULL OR expected_turns_kind IN ('finite', 'infinite', 'unavailable')),
	CONSTRAINT battle_inference_cases_result_shape_ck CHECK ((status IN ('pending', 'running') AND result_fingerprint IS NULL) OR (status = 'succeeded' AND attacker_win_numerator IS NOT NULL AND attacker_win_denominator IS NOT NULL AND defender_win_numerator IS NOT NULL AND defender_win_denominator IS NOT NULL AND draw_numerator IS NOT NULL AND draw_denominator IS NOT NULL AND expected_turns_kind IS NOT NULL AND failure_code IS NULL AND diagnostic IS NULL AND result_fingerprint IS NOT NULL) OR (status IN ('failed', 'truncated', 'cancelled') AND attacker_win_numerator IS NULL AND attacker_win_denominator IS NULL AND defender_win_numerator IS NULL AND defender_win_denominator IS NULL AND draw_numerator IS NULL AND draw_denominator IS NULL AND expected_turns_kind IS NULL AND expected_turns_numerator IS NULL AND expected_turns_denominator IS NULL AND failure_code IS NOT NULL AND diagnostic IS NOT NULL AND result_fingerprint IS NOT NULL)),
	FOREIGN KEY(job_id) REFERENCES poke_runtime.battle_inference_jobs (job_id) ON DELETE CASCADE
);

CREATE INDEX battle_inference_cases_attacker_config_idx ON poke_runtime.battle_inference_cases (job_id, attacker_configuration_id, sequence_no);

CREATE INDEX battle_inference_cases_claim_idx ON poke_runtime.battle_inference_cases (job_id, status, lease_expires_at, sequence_no);

CREATE INDEX battle_inference_cases_defender_config_idx ON poke_runtime.battle_inference_cases (job_id, defender_configuration_id, sequence_no);

CREATE INDEX battle_inference_cases_failure_idx ON poke_runtime.battle_inference_cases (job_id, failure_code, sequence_no);

CREATE TABLE poke_runtime.battle_inference_job_execution_specs (
	job_id TEXT NOT NULL,
	contract_version TEXT NOT NULL,
	weight_assumption VARCHAR(64) NOT NULL,
	attacker_policy VARCHAR(64) NOT NULL,
	defender_policy VARCHAR(64) NOT NULL,
	mechanism_admission VARCHAR(64) NOT NULL,
	process_count INTEGER NOT NULL,
	queue_depth INTEGER NOT NULL,
	max_nodes_per_pair INTEGER NOT NULL,
	max_edges_per_pair INTEGER NOT NULL,
	max_turns INTEGER,
	PRIMARY KEY (job_id),
	CONSTRAINT battle_inference_job_execution_process_count_ck CHECK (process_count BETWEEN 1 AND 8),
	CONSTRAINT battle_inference_job_execution_queue_depth_ck CHECK (queue_depth BETWEEN process_count AND 32),
	CONSTRAINT battle_inference_job_execution_nodes_ck CHECK (max_nodes_per_pair BETWEEN 1 AND 2000000),
	CONSTRAINT battle_inference_job_execution_edges_ck CHECK (max_edges_per_pair BETWEEN 1 AND 8000000),
	CONSTRAINT battle_inference_job_execution_turns_ck CHECK (max_turns IS NULL OR max_turns BETWEEN 1 AND 10000),
	FOREIGN KEY(job_id) REFERENCES poke_runtime.battle_inference_jobs (job_id) ON DELETE CASCADE
);

CREATE TABLE poke_runtime.battle_inference_job_progress (
	job_id TEXT NOT NULL,
	total_count INTEGER NOT NULL,
	pending_count INTEGER NOT NULL,
	running_count INTEGER NOT NULL,
	succeeded_count INTEGER NOT NULL,
	failed_count INTEGER NOT NULL,
	truncated_count INTEGER NOT NULL,
	cancelled_count INTEGER NOT NULL,
	cumulative_node_count BIGINT NOT NULL,
	cumulative_edge_count BIGINT NOT NULL,
	budget_consumed BIGINT NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (job_id),
	CONSTRAINT battle_inference_job_progress_count_ck CHECK (total_count = pending_count + running_count + succeeded_count + failed_count + truncated_count + cancelled_count),
	CONSTRAINT battle_inference_job_progress_nonnegative_ck CHECK (total_count >= 0 AND pending_count >= 0 AND running_count >= 0 AND succeeded_count >= 0 AND failed_count >= 0 AND truncated_count >= 0 AND cancelled_count >= 0 AND cumulative_node_count >= 0 AND cumulative_edge_count >= 0 AND budget_consumed >= 0),
	FOREIGN KEY(job_id) REFERENCES poke_runtime.battle_inference_jobs (job_id) ON DELETE CASCADE
);
