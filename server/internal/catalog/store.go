// Package catalog 查询既有 PostgreSQL 物化视图，不复制知识数据或战斗规则。
package catalog

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"strings"
)

// ErrInvalidFilter 表示调用者选择了当前规则集不存在的属性。
var ErrInvalidFilter = errors.New("unsupported move type")

// Store 持有服务借用的连接池；所有 SQL 均绑定外部参数。
type Store struct{ db *sql.DB }

// New 以 db 创建读取端口；不隐式导入 CSV 或刷新物化视图。
func New(db *sql.DB) *Store { return &Store{db} }

// PokemonJSON 返回现有物化视图映射成的原 HTTP 字段，避免驱动数组差异。
func (store *Store) PokemonJSON(ctx context.Context, ruleset, query string, limit, id int, detail bool) (json.RawMessage, error) {
	querySQL := `SELECT COALESCE(jsonb_agg(payload),'[]'::jsonb) FROM (SELECT jsonb_build_object('pokemon_id',pokemon_id,'identifier',pokemon_identifier,'display_name',COALESCE(pokemon_name,pokemon_identifier),'form_identifier',form_identifier,'types',array_remove(ARRAY[type_1_identifier,type_2_identifier],NULL),'type_names',array_remove(ARRAY[type_1_name,type_2_name],NULL),'sprite_url','/api/v1/assets/pokemon/'||pokemon_id||'/sprite?ruleset_id='||$1||'&slot=front_default')`
	if detail {
		querySQL += `||jsonb_build_object('base_stats',jsonb_build_object('hp',hp,'attack',attack,'defense',defense,'special_attack',special_attack,'special_defense',special_defense,'speed',speed))`
	}
	querySQL += ` AS payload FROM poke_champion.pokemon_profile_mv WHERE ruleset_id=$1 AND ($2='' OR pokemon_identifier ILIKE $3 OR pokemon_name ILIKE $3) AND ($4=0 OR pokemon_id=$4) ORDER BY pokemon_id,form_identifier NULLS FIRST,pokemon_identifier LIMIT $5) selected`
	var result json.RawMessage
	err := store.db.QueryRowContext(ctx, querySQL, ruleset, strings.TrimSpace(query), "%"+strings.TrimSpace(query)+"%", id, limit).Scan(&result)
	if err != nil {
		return nil, err
	}
	if detail {
		var entries []json.RawMessage
		if err = json.Unmarshal(result, &entries); err != nil {
			return nil, err
		}
		if len(entries) == 0 {
			return nil, sql.ErrNoRows
		}
		return entries[0], nil
	}
	return result, nil
}

// TypeOption 保持完整规则集属性元数据，不从当前分页推断可用值。
type TypeOption struct {
	Identifier  string `json:"identifier"`
	DisplayName string `json:"display_name"`
}

// MovePage 保留稳定分页和去重总数。
type MovePage struct {
	Items          json.RawMessage `json:"items"`
	Total          int             `json:"total"`
	Limit          int             `json:"limit"`
	Offset         int             `json:"offset"`
	HasMore        bool            `json:"has_more"`
	AvailableTypes []TypeOption    `json:"available_types"`
}

const filteredMoves = `WITH filtered_moves AS(SELECT DISTINCT ON(move_id) move_id,move_identifier,COALESCE(move_name,move_identifier) AS move_name,type_identifier,COALESCE(type_name,type_identifier) AS type_name,damage_class_identifier,power FROM poke_champion.pokemon_learnset_mv WHERE ruleset_id=$1 AND pokemon_id=$2 AND damage_class_identifier IN('physical','special') AND power>0 AND ($3='all' OR damage_class_identifier=$3) AND (cardinality($4::text[])=0 OR type_identifier=ANY($4::text[])) AND ($5='' OR move_identifier ILIKE $6 OR move_name ILIKE $6) ORDER BY move_id,move_identifier)`

// Moves 在同一只读快照中读取属性、去重总数和页面，杜绝刷新时总数漂移。
// types 包含非法值时返回 ErrInvalidFilter，不执行部分过滤。
func (store *Store) Moves(ctx context.Context, ruleset string, pokemon int, query, category string, types []string, limit, offset int) (MovePage, error) {
	result := MovePage{Items: json.RawMessage(`[]`), Limit: limit, Offset: offset, AvailableTypes: []TypeOption{}}
	tx, err := store.db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return result, err
	}
	defer tx.Rollback()
	rows, err := tx.QueryContext(ctx, `SELECT DISTINCT damage_type_id,damage_type_identifier,COALESCE(damage_type_name,damage_type_identifier) FROM poke_champion.type_efficacy_mv WHERE ruleset_id=$1 ORDER BY damage_type_id`, ruleset)
	if err != nil {
		return result, err
	}
	allowed := map[string]bool{}
	for rows.Next() {
		var id int
		var option TypeOption
		if err = rows.Scan(&id, &option.Identifier, &option.DisplayName); err != nil {
			rows.Close()
			return result, err
		}
		result.AvailableTypes = append(result.AvailableTypes, option)
		allowed[option.Identifier] = true
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return result, err
	}
	for _, identifier := range types {
		if !allowed[identifier] {
			return result, ErrInvalidFilter
		}
	}
	if types == nil {
		types = []string{}
	}
	args := []any{ruleset, pokemon, category, types, strings.TrimSpace(query), "%" + strings.TrimSpace(query) + "%"}
	if err = tx.QueryRowContext(ctx, filteredMoves+` SELECT COUNT(*) FROM filtered_moves`, args...).Scan(&result.Total); err != nil {
		return result, err
	}
	args = append(args, limit, offset)
	err = tx.QueryRowContext(ctx, filteredMoves+` SELECT COALESCE(jsonb_agg(payload),'[]'::jsonb) FROM(SELECT jsonb_build_object('move_id',move_id,'identifier',move_identifier,'display_name',move_name,'type',type_identifier,'type_name',type_name,'category',damage_class_identifier,'power',power) payload FROM filtered_moves ORDER BY power DESC,type_identifier DESC,move_id,move_identifier LIMIT $7 OFFSET $8) selected`, args...).Scan(&result.Items)
	if err != nil {
		return result, err
	}
	var page []json.RawMessage
	if err = json.Unmarshal(result.Items, &page); err != nil {
		return result, err
	}
	result.HasMore = offset+len(page) < result.Total
	return result, tx.Commit()
}

// Abilities 依据 generation 还原历史能力槽位，保留旧引擎的 implemented 标记。
// 标记表示既有领域能力，不承诺尚未迁移的完整回合机制。
func (store *Store) Abilities(ctx context.Context, ruleset string, pokemon int) (json.RawMessage, error) {
	var result json.RawMessage
	err := store.db.QueryRowContext(ctx, `WITH context AS(SELECT generation_id,language_id FROM poke_champion.ruleset_context_mv WHERE ruleset_id=$1 LIMIT 1),resolved AS(SELECT pa.slot,pa.is_hidden,CASE WHEN past.ability_id IS NOT NULL THEN NULLIF(past.ability_id,0) ELSE NULLIF(pa.ability_id,0) END ability_id FROM poke_raw.pokemon_abilities pa CROSS JOIN context rc LEFT JOIN LATERAL(SELECT pap.ability_id FROM poke_raw.pokemon_abilities_past pap WHERE pap.pokemon_id=pa.pokemon_id AND pap.slot=pa.slot AND pap.is_hidden=pa.is_hidden AND pap.generation_id>=rc.generation_id ORDER BY pap.generation_id LIMIT 1) past ON true WHERE pa.pokemon_id=$2) SELECT COALESCE(jsonb_agg(payload),'[]'::jsonb) FROM(SELECT jsonb_build_object('ability_id',a.id,'identifier',a.identifier,'display_name',COALESCE(n.name,a.identifier),'slot',resolved.slot,'is_hidden',resolved.is_hidden,'implemented',a.identifier=ANY(ARRAY['technician','adaptability','thick-fat','filter','solid-rock','sniper','multiscale','inner-focus'])) payload FROM resolved CROSS JOIN context rc JOIN poke_raw.abilities a ON a.id=resolved.ability_id AND a.is_main_series IS TRUE LEFT JOIN poke_raw.ability_names n ON n.ability_id=a.id AND n.local_language_id=rc.language_id ORDER BY resolved.slot,resolved.is_hidden,a.id) selected`, ruleset, pokemon).Scan(&result)
	return result, err
}

// Items 返回保留 generation/道具分类过滤的旧实现选项及显式无道具项。
func (store *Store) Items(ctx context.Context, ruleset string) (json.RawMessage, error) {
	var result json.RawMessage
	err := store.db.QueryRowContext(ctx, `WITH context AS(SELECT generation_id,language_id FROM poke_champion.ruleset_context_mv WHERE ruleset_id=$1 LIMIT 1),flags AS(SELECT map.item_id,bool_or(flag.identifier='holdable') holdable,bool_or(flag.identifier IN('holdable-active','holdable-passive')) battle_holdable FROM poke_raw.item_flag_map map JOIN poke_raw.item_flags flag ON flag.id=map.item_flag_id GROUP BY map.item_id) SELECT jsonb_build_array(jsonb_build_object('item_id',NULL,'identifier','none','display_name','不携带道具','effect_identifier',NULL,'sprite_url',NULL))||COALESCE(jsonb_agg(payload),'[]'::jsonb) FROM(SELECT jsonb_build_object('item_id',i.id,'identifier',i.identifier,'display_name',COALESCE(n.name,i.identifier),'effect_identifier',i.identifier,'sprite_url','/api/v1/assets/items/'||i.identifier||'/sprite') payload FROM poke_raw.items i JOIN poke_raw.item_categories c ON c.id=i.category_id CROSS JOIN context rc LEFT JOIN flags f ON f.item_id=i.id LEFT JOIN poke_raw.item_names n ON n.item_id=i.id AND n.local_language_id=rc.language_id WHERE i.identifier=ANY(ARRAY['life-orb','choice-band','choice-specs','expert-belt','eviolite']) AND ((f.holdable IS TRUE AND f.battle_holdable IS TRUE) OR c.identifier IN('held-items','choice','type-enhancement','bad-held-items','plates')) AND EXISTS(SELECT 1 FROM poke_raw.item_game_indices ig WHERE ig.item_id=i.id AND ig.generation_id<=rc.generation_id) ORDER BY i.id) selected`, ruleset).Scan(&result)
	return result, err
}
