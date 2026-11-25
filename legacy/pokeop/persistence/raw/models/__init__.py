# Auto-generated. DO NOT EDIT BY HAND.
from pokeop.persistence.raw.models.base import Base
from pokeop.persistence.raw.models.abilities import Abilities
from pokeop.persistence.raw.models.ability_changelog import AbilityChangelog
from pokeop.persistence.raw.models.ability_changelog_prose import AbilityChangelogProse
from pokeop.persistence.raw.models.ability_flavor_text import AbilityFlavorText
from pokeop.persistence.raw.models.ability_names import AbilityNames
from pokeop.persistence.raw.models.ability_prose import AbilityProse
from pokeop.persistence.raw.models.berries import Berries
from pokeop.persistence.raw.models.berry_firmness import BerryFirmness
from pokeop.persistence.raw.models.berry_firmness_names import BerryFirmnessNames
from pokeop.persistence.raw.models.berry_flavors import BerryFlavors
from pokeop.persistence.raw.models.characteristic_text import CharacteristicText
from pokeop.persistence.raw.models.characteristics import Characteristics
from pokeop.persistence.raw.models.conquest_episode_names import ConquestEpisodeNames
from pokeop.persistence.raw.models.conquest_episode_warriors import ConquestEpisodeWarriors
from pokeop.persistence.raw.models.conquest_episodes import ConquestEpisodes
from pokeop.persistence.raw.models.conquest_kingdom_names import ConquestKingdomNames
from pokeop.persistence.raw.models.conquest_kingdoms import ConquestKingdoms
from pokeop.persistence.raw.models.conquest_max_links import ConquestMaxLinks
from pokeop.persistence.raw.models.conquest_move_data import ConquestMoveData
from pokeop.persistence.raw.models.conquest_move_displacement_prose import ConquestMoveDisplacementProse
from pokeop.persistence.raw.models.conquest_move_displacements import ConquestMoveDisplacements
from pokeop.persistence.raw.models.conquest_move_effect_prose import ConquestMoveEffectProse
from pokeop.persistence.raw.models.conquest_move_effects import ConquestMoveEffects
from pokeop.persistence.raw.models.conquest_move_range_prose import ConquestMoveRangeProse
from pokeop.persistence.raw.models.conquest_move_ranges import ConquestMoveRanges
from pokeop.persistence.raw.models.conquest_pokemon_abilities import ConquestPokemonAbilities
from pokeop.persistence.raw.models.conquest_pokemon_evolution import ConquestPokemonEvolution
from pokeop.persistence.raw.models.conquest_pokemon_moves import ConquestPokemonMoves
from pokeop.persistence.raw.models.conquest_pokemon_stats import ConquestPokemonStats
from pokeop.persistence.raw.models.conquest_stat_names import ConquestStatNames
from pokeop.persistence.raw.models.conquest_stats import ConquestStats
from pokeop.persistence.raw.models.conquest_transformation_pokemon import ConquestTransformationPokemon
from pokeop.persistence.raw.models.conquest_transformation_warriors import ConquestTransformationWarriors
from pokeop.persistence.raw.models.conquest_warrior_archetypes import ConquestWarriorArchetypes
from pokeop.persistence.raw.models.conquest_warrior_names import ConquestWarriorNames
from pokeop.persistence.raw.models.conquest_warrior_rank_stat_map import ConquestWarriorRankStatMap
from pokeop.persistence.raw.models.conquest_warrior_ranks import ConquestWarriorRanks
from pokeop.persistence.raw.models.conquest_warrior_skill_names import ConquestWarriorSkillNames
from pokeop.persistence.raw.models.conquest_warrior_skills import ConquestWarriorSkills
from pokeop.persistence.raw.models.conquest_warrior_specialties import ConquestWarriorSpecialties
from pokeop.persistence.raw.models.conquest_warrior_stat_names import ConquestWarriorStatNames
from pokeop.persistence.raw.models.conquest_warrior_stats import ConquestWarriorStats
from pokeop.persistence.raw.models.conquest_warrior_transformation import ConquestWarriorTransformation
from pokeop.persistence.raw.models.conquest_warriors import ConquestWarriors
from pokeop.persistence.raw.models.contest_combos import ContestCombos
from pokeop.persistence.raw.models.contest_effect_prose import ContestEffectProse
from pokeop.persistence.raw.models.contest_effects import ContestEffects
from pokeop.persistence.raw.models.contest_type_names import ContestTypeNames
from pokeop.persistence.raw.models.contest_types import ContestTypes
from pokeop.persistence.raw.models.egg_group_prose import EggGroupProse
from pokeop.persistence.raw.models.egg_groups import EggGroups
from pokeop.persistence.raw.models.encounter_condition_prose import EncounterConditionProse
from pokeop.persistence.raw.models.encounter_condition_value_map import EncounterConditionValueMap
from pokeop.persistence.raw.models.encounter_condition_value_prose import EncounterConditionValueProse
from pokeop.persistence.raw.models.encounter_condition_values import EncounterConditionValues
from pokeop.persistence.raw.models.encounter_conditions import EncounterConditions
from pokeop.persistence.raw.models.encounter_method_prose import EncounterMethodProse
from pokeop.persistence.raw.models.encounter_methods import EncounterMethods
from pokeop.persistence.raw.models.encounter_slots import EncounterSlots
from pokeop.persistence.raw.models.encounters import Encounters
from pokeop.persistence.raw.models.evolution_chains import EvolutionChains
from pokeop.persistence.raw.models.evolution_trigger_prose import EvolutionTriggerProse
from pokeop.persistence.raw.models.evolution_triggers import EvolutionTriggers
from pokeop.persistence.raw.models.experience import Experience
from pokeop.persistence.raw.models.genders import Genders
from pokeop.persistence.raw.models.generation_names import GenerationNames
from pokeop.persistence.raw.models.generations import Generations
from pokeop.persistence.raw.models.growth_rate_prose import GrowthRateProse
from pokeop.persistence.raw.models.growth_rates import GrowthRates
from pokeop.persistence.raw.models.item_categories import ItemCategories
from pokeop.persistence.raw.models.item_category_prose import ItemCategoryProse
from pokeop.persistence.raw.models.item_flag_map import ItemFlagMap
from pokeop.persistence.raw.models.item_flag_prose import ItemFlagProse
from pokeop.persistence.raw.models.item_flags import ItemFlags
from pokeop.persistence.raw.models.item_flavor_summaries import ItemFlavorSummaries
from pokeop.persistence.raw.models.item_flavor_text import ItemFlavorText
from pokeop.persistence.raw.models.item_fling_effect_prose import ItemFlingEffectProse
from pokeop.persistence.raw.models.item_fling_effects import ItemFlingEffects
from pokeop.persistence.raw.models.item_game_indices import ItemGameIndices
from pokeop.persistence.raw.models.item_names import ItemNames
from pokeop.persistence.raw.models.item_pocket_names import ItemPocketNames
from pokeop.persistence.raw.models.item_pockets import ItemPockets
from pokeop.persistence.raw.models.item_prose import ItemProse
from pokeop.persistence.raw.models.items import Items
from pokeop.persistence.raw.models.language_names import LanguageNames
from pokeop.persistence.raw.models.languages import Languages
from pokeop.persistence.raw.models.location_area_encounter_rates import LocationAreaEncounterRates
from pokeop.persistence.raw.models.location_area_prose import LocationAreaProse
from pokeop.persistence.raw.models.location_areas import LocationAreas
from pokeop.persistence.raw.models.location_game_indices import LocationGameIndices
from pokeop.persistence.raw.models.location_names import LocationNames
from pokeop.persistence.raw.models.locations import Locations
from pokeop.persistence.raw.models.machines import Machines
from pokeop.persistence.raw.models.move_battle_style_prose import MoveBattleStyleProse
from pokeop.persistence.raw.models.move_battle_styles import MoveBattleStyles
from pokeop.persistence.raw.models.move_changelog import MoveChangelog
from pokeop.persistence.raw.models.move_damage_class_prose import MoveDamageClassProse
from pokeop.persistence.raw.models.move_damage_classes import MoveDamageClasses
from pokeop.persistence.raw.models.move_effect_changelog import MoveEffectChangelog
from pokeop.persistence.raw.models.move_effect_changelog_prose import MoveEffectChangelogProse
from pokeop.persistence.raw.models.move_effect_prose import MoveEffectProse
from pokeop.persistence.raw.models.move_effects import MoveEffects
from pokeop.persistence.raw.models.move_flag_map import MoveFlagMap
from pokeop.persistence.raw.models.move_flag_prose import MoveFlagProse
from pokeop.persistence.raw.models.move_flags import MoveFlags
from pokeop.persistence.raw.models.move_flavor_summaries import MoveFlavorSummaries
from pokeop.persistence.raw.models.move_flavor_text import MoveFlavorText
from pokeop.persistence.raw.models.move_meta import MoveMeta
from pokeop.persistence.raw.models.move_meta_ailment_names import MoveMetaAilmentNames
from pokeop.persistence.raw.models.move_meta_ailments import MoveMetaAilments
from pokeop.persistence.raw.models.move_meta_categories import MoveMetaCategories
from pokeop.persistence.raw.models.move_meta_category_prose import MoveMetaCategoryProse
from pokeop.persistence.raw.models.move_meta_stat_changes import MoveMetaStatChanges
from pokeop.persistence.raw.models.move_names import MoveNames
from pokeop.persistence.raw.models.move_target_prose import MoveTargetProse
from pokeop.persistence.raw.models.move_targets import MoveTargets
from pokeop.persistence.raw.models.moves import Moves
from pokeop.persistence.raw.models.nature_battle_style_preferences import NatureBattleStylePreferences
from pokeop.persistence.raw.models.nature_names import NatureNames
from pokeop.persistence.raw.models.nature_pokeathlon_stats import NaturePokeathlonStats
from pokeop.persistence.raw.models.natures import Natures
from pokeop.persistence.raw.models.pal_park import PalPark
from pokeop.persistence.raw.models.pal_park_area_names import PalParkAreaNames
from pokeop.persistence.raw.models.pal_park_areas import PalParkAreas
from pokeop.persistence.raw.models.pokeathlon_stat_names import PokeathlonStatNames
from pokeop.persistence.raw.models.pokeathlon_stats import PokeathlonStats
from pokeop.persistence.raw.models.pokedex_prose import PokedexProse
from pokeop.persistence.raw.models.pokedex_version_groups import PokedexVersionGroups
from pokeop.persistence.raw.models.pokedexes import Pokedexes
from pokeop.persistence.raw.models.pokemon import Pokemon
from pokeop.persistence.raw.models.pokemon_abilities import PokemonAbilities
from pokeop.persistence.raw.models.pokemon_abilities_past import PokemonAbilitiesPast
from pokeop.persistence.raw.models.pokemon_color_names import PokemonColorNames
from pokeop.persistence.raw.models.pokemon_colors import PokemonColors
from pokeop.persistence.raw.models.pokemon_dex_numbers import PokemonDexNumbers
from pokeop.persistence.raw.models.pokemon_egg_groups import PokemonEggGroups
from pokeop.persistence.raw.models.pokemon_evolution import PokemonEvolution
from pokeop.persistence.raw.models.pokemon_form_generations import PokemonFormGenerations
from pokeop.persistence.raw.models.pokemon_form_names import PokemonFormNames
from pokeop.persistence.raw.models.pokemon_form_pokeathlon_stats import PokemonFormPokeathlonStats
from pokeop.persistence.raw.models.pokemon_form_types import PokemonFormTypes
from pokeop.persistence.raw.models.pokemon_forms import PokemonForms
from pokeop.persistence.raw.models.pokemon_game_indices import PokemonGameIndices
from pokeop.persistence.raw.models.pokemon_habitat_names import PokemonHabitatNames
from pokeop.persistence.raw.models.pokemon_habitats import PokemonHabitats
from pokeop.persistence.raw.models.pokemon_items import PokemonItems
from pokeop.persistence.raw.models.pokemon_move_method_prose import PokemonMoveMethodProse
from pokeop.persistence.raw.models.pokemon_move_methods import PokemonMoveMethods
from pokeop.persistence.raw.models.pokemon_moves import PokemonMoves
from pokeop.persistence.raw.models.pokemon_shape_prose import PokemonShapeProse
from pokeop.persistence.raw.models.pokemon_shapes import PokemonShapes
from pokeop.persistence.raw.models.pokemon_species import PokemonSpecies
from pokeop.persistence.raw.models.pokemon_species_flavor_summaries import PokemonSpeciesFlavorSummaries
from pokeop.persistence.raw.models.pokemon_species_flavor_text import PokemonSpeciesFlavorText
from pokeop.persistence.raw.models.pokemon_species_names import PokemonSpeciesNames
from pokeop.persistence.raw.models.pokemon_species_prose import PokemonSpeciesProse
from pokeop.persistence.raw.models.pokemon_stats import PokemonStats
from pokeop.persistence.raw.models.pokemon_types import PokemonTypes
from pokeop.persistence.raw.models.pokemon_types_past import PokemonTypesPast
from pokeop.persistence.raw.models.region_names import RegionNames
from pokeop.persistence.raw.models.regions import Regions
from pokeop.persistence.raw.models.stat_names import StatNames
from pokeop.persistence.raw.models.stats import Stats
from pokeop.persistence.raw.models.super_contest_combos import SuperContestCombos
from pokeop.persistence.raw.models.super_contest_effect_prose import SuperContestEffectProse
from pokeop.persistence.raw.models.super_contest_effects import SuperContestEffects
from pokeop.persistence.raw.models.translations_cs import TranslationsCs
from pokeop.persistence.raw.models.type_efficacy import TypeEfficacy
from pokeop.persistence.raw.models.type_efficacy_past import TypeEfficacyPast
from pokeop.persistence.raw.models.type_game_indices import TypeGameIndices
from pokeop.persistence.raw.models.type_names import TypeNames
from pokeop.persistence.raw.models.types import Types
from pokeop.persistence.raw.models.version_group_pokemon_move_methods import VersionGroupPokemonMoveMethods
from pokeop.persistence.raw.models.version_group_regions import VersionGroupRegions
from pokeop.persistence.raw.models.version_groups import VersionGroups
from pokeop.persistence.raw.models.version_names import VersionNames
from pokeop.persistence.raw.models.versions import Versions

# fmt: off
__all__ = [
    'Base',
    'Abilities',
    'AbilityChangelog',
    'AbilityChangelogProse',
    'AbilityFlavorText',
    'AbilityNames',
    'AbilityProse',
    'Berries',
    'BerryFirmness',
    'BerryFirmnessNames',
    'BerryFlavors',
    'CharacteristicText',
    'Characteristics',
    'ConquestEpisodeNames',
    'ConquestEpisodeWarriors',
    'ConquestEpisodes',
    'ConquestKingdomNames',
    'ConquestKingdoms',
    'ConquestMaxLinks',
    'ConquestMoveData',
    'ConquestMoveDisplacementProse',
    'ConquestMoveDisplacements',
    'ConquestMoveEffectProse',
    'ConquestMoveEffects',
    'ConquestMoveRangeProse',
    'ConquestMoveRanges',
    'ConquestPokemonAbilities',
    'ConquestPokemonEvolution',
    'ConquestPokemonMoves',
    'ConquestPokemonStats',
    'ConquestStatNames',
    'ConquestStats',
    'ConquestTransformationPokemon',
    'ConquestTransformationWarriors',
    'ConquestWarriorArchetypes',
    'ConquestWarriorNames',
    'ConquestWarriorRankStatMap',
    'ConquestWarriorRanks',
    'ConquestWarriorSkillNames',
    'ConquestWarriorSkills',
    'ConquestWarriorSpecialties',
    'ConquestWarriorStatNames',
    'ConquestWarriorStats',
    'ConquestWarriorTransformation',
    'ConquestWarriors',
    'ContestCombos',
    'ContestEffectProse',
    'ContestEffects',
    'ContestTypeNames',
    'ContestTypes',
    'EggGroupProse',
    'EggGroups',
    'EncounterConditionProse',
    'EncounterConditionValueMap',
    'EncounterConditionValueProse',
    'EncounterConditionValues',
    'EncounterConditions',
    'EncounterMethodProse',
    'EncounterMethods',
    'EncounterSlots',
    'Encounters',
    'EvolutionChains',
    'EvolutionTriggerProse',
    'EvolutionTriggers',
    'Experience',
    'Genders',
    'GenerationNames',
    'Generations',
    'GrowthRateProse',
    'GrowthRates',
    'ItemCategories',
    'ItemCategoryProse',
    'ItemFlagMap',
    'ItemFlagProse',
    'ItemFlags',
    'ItemFlavorSummaries',
    'ItemFlavorText',
    'ItemFlingEffectProse',
    'ItemFlingEffects',
    'ItemGameIndices',
    'ItemNames',
    'ItemPocketNames',
    'ItemPockets',
    'ItemProse',
    'Items',
    'LanguageNames',
    'Languages',
    'LocationAreaEncounterRates',
    'LocationAreaProse',
    'LocationAreas',
    'LocationGameIndices',
    'LocationNames',
    'Locations',
    'Machines',
    'MoveBattleStyleProse',
    'MoveBattleStyles',
    'MoveChangelog',
    'MoveDamageClassProse',
    'MoveDamageClasses',
    'MoveEffectChangelog',
    'MoveEffectChangelogProse',
    'MoveEffectProse',
    'MoveEffects',
    'MoveFlagMap',
    'MoveFlagProse',
    'MoveFlags',
    'MoveFlavorSummaries',
    'MoveFlavorText',
    'MoveMeta',
    'MoveMetaAilmentNames',
    'MoveMetaAilments',
    'MoveMetaCategories',
    'MoveMetaCategoryProse',
    'MoveMetaStatChanges',
    'MoveNames',
    'MoveTargetProse',
    'MoveTargets',
    'Moves',
    'NatureBattleStylePreferences',
    'NatureNames',
    'NaturePokeathlonStats',
    'Natures',
    'PalPark',
    'PalParkAreaNames',
    'PalParkAreas',
    'PokeathlonStatNames',
    'PokeathlonStats',
    'PokedexProse',
    'PokedexVersionGroups',
    'Pokedexes',
    'Pokemon',
    'PokemonAbilities',
    'PokemonAbilitiesPast',
    'PokemonColorNames',
    'PokemonColors',
    'PokemonDexNumbers',
    'PokemonEggGroups',
    'PokemonEvolution',
    'PokemonFormGenerations',
    'PokemonFormNames',
    'PokemonFormPokeathlonStats',
    'PokemonFormTypes',
    'PokemonForms',
    'PokemonGameIndices',
    'PokemonHabitatNames',
    'PokemonHabitats',
    'PokemonItems',
    'PokemonMoveMethodProse',
    'PokemonMoveMethods',
    'PokemonMoves',
    'PokemonShapeProse',
    'PokemonShapes',
    'PokemonSpecies',
    'PokemonSpeciesFlavorSummaries',
    'PokemonSpeciesFlavorText',
    'PokemonSpeciesNames',
    'PokemonSpeciesProse',
    'PokemonStats',
    'PokemonTypes',
    'PokemonTypesPast',
    'RegionNames',
    'Regions',
    'StatNames',
    'Stats',
    'SuperContestCombos',
    'SuperContestEffectProse',
    'SuperContestEffects',
    'TranslationsCs',
    'TypeEfficacy',
    'TypeEfficacyPast',
    'TypeGameIndices',
    'TypeNames',
    'Types',
    'VersionGroupPokemonMoveMethods',
    'VersionGroupRegions',
    'VersionGroups',
    'VersionNames',
    'Versions',
]
# fmt: on
