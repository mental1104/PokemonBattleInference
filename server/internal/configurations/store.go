package configurations

import (
	"context"
	"crypto/rand"
	"database/sql"
	"errors"
	"fmt"
	"sort"
)

// ErrNotFound 表示当前租户没有对应的有效对象，不泄漏其他租户数据。
var ErrNotFound = errors.New("custom configuration not found")

// ErrInvalidPreference 表示显示偏好引用或角色非法，区别于不可公开的数据库错误。
var ErrInvalidPreference = errors.New("invalid configuration preference")

// Store 在原 poke_runtime 表中持久化预设，连接池由服务拥有。
type Store struct{ db *sql.DB }

// New 绑定 db，不创建连接或执行隐式迁移。
func New(db *sql.DB) *Store { return &Store{db: db} }

// rowScanner 表达 Row/Rows 的共同读取合同，避免数据库对象泄漏到 HTTP 层。
type rowScanner interface{ Scan(...any) error }

const columns = `id,name,nature_id,role,binding_kind,pokemon_id,ev_hp,ev_attack,ev_defense,ev_special_attack,ev_special_defense,ev_speed,iv_hp,iv_attack,iv_defense,iv_special_attack,iv_special_defense,iv_speed,updated_at`

// scanView 从 row 读取独立值，返回拥有完整快照的自定义配置或原始 SQL 错误。
func scanView(row rowScanner) (View, error) {
	view := View{Source: "custom", SortOrder: 11000, Description: "租户共享自定义配置。"}
	err := row.Scan(&view.Key, &view.Name, &view.NatureID, &view.Role, &view.BindingKind, &view.PokemonID, &view.EVs.HP, &view.EVs.Attack, &view.EVs.Defense, &view.EVs.SpecialAttack, &view.EVs.SpecialDefense, &view.EVs.Speed, &view.IVs.HP, &view.IVs.Attack, &view.IVs.Defense, &view.IVs.SpecialAttack, &view.IVs.SpecialDefense, &view.IVs.Speed, &view.UpdatedAt)
	return finalize(view), err
}

// ListResult 同时返回管理列表和未隐藏列表，沿用六项默认显示上限。
type ListResult struct {
	Items               []View  `json:"items"`
	VisibleItems        []View  `json:"visible_items"`
	DefaultVisibleLimit int     `json:"default_visible_limit"`
	FallbackID          *string `json:"fallback_id"`
}

// List 在同一只读快照内合并 tenant 的角色与 pokemon 绑定配置和偏好。
// includeHidden 仅决定 Items，VisibleItems 始终过滤隐藏项；所有排序键稳定。
func (store *Store) List(ctx context.Context, tenant, role string, pokemon int, includeHidden bool) (ListResult, error) {
	result := ListResult{Items: []View{}, VisibleItems: []View{}, DefaultVisibleLimit: 6}
	tx, err := store.db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if err != nil {
		return result, err
	}
	defer tx.Rollback()
	views := builtins()
	rows, err := tx.QueryContext(ctx, `SELECT `+columns+` FROM poke_runtime.stat_configurations WHERE tenant_id=$1 AND NOT is_deleted ORDER BY created_at,id`, tenant)
	if err != nil {
		return result, err
	}
	for rows.Next() {
		view, scanErr := scanView(rows)
		if scanErr != nil {
			rows.Close()
			return result, scanErr
		}
		views = append(views, view)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return result, err
	}
	type preference struct {
		order  int
		hidden bool
	}
	prefs := map[Reference]preference{}
	rows, err = tx.QueryContext(ctx, `SELECT reference_type,reference_key,sort_order,hidden FROM poke_runtime.stat_configuration_preferences WHERE tenant_id=$1 AND role=$2`, tenant, role)
	if err != nil {
		return result, err
	}
	for rows.Next() {
		var ref Reference
		var pref preference
		if err = rows.Scan(&ref.Source, &ref.Key, &pref.order, &pref.hidden); err != nil {
			rows.Close()
			return result, err
		}
		prefs[ref] = pref
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return result, err
	}
	if err = tx.Commit(); err != nil {
		return result, err
	}
	filtered := make([]View, 0, len(views))
	for _, view := range views {
		if view.Role != "both" && view.Role != role {
			continue
		}
		if view.PokemonID != nil && *view.PokemonID != pokemon {
			continue
		}
		if pref, ok := prefs[Reference{view.Source, view.Key}]; ok {
			view.SortOrder = pref.order
			view.Hidden = pref.hidden
		}
		filtered = append(filtered, finalize(view))
	}
	sort.SliceStable(filtered, func(i, j int) bool {
		a, b := filtered[i], filtered[j]
		if a.Hidden != b.Hidden {
			return !a.Hidden
		}
		if a.SortOrder != b.SortOrder {
			return a.SortOrder < b.SortOrder
		}
		if a.Source != b.Source {
			return a.Source < b.Source
		}
		if a.Name != b.Name {
			return a.Name < b.Name
		}
		return a.ID < b.ID
	})
	for _, view := range filtered {
		if !view.Hidden {
			result.VisibleItems = append(result.VisibleItems, view)
		}
		if includeHidden || !view.Hidden {
			result.Items = append(result.Items, view)
		}
	}
	if len(result.VisibleItems) > 0 {
		id := result.VisibleItems[0].ID
		result.FallbackID = &id
	}
	return result, nil
}

// Save 原子创建或完整更新 tenant 的有效配置，id 为空时生成 UUIDv4。
// 输入先校验；更新不存在或属于其他租户的 id 时返回 ErrNotFound。
func (store *Store) Save(ctx context.Context, tenant, id string, command Command) (View, error) {
	if err := command.Validate(); err != nil {
		return View{}, err
	}
	create := id == ""
	if create {
		var raw [16]byte
		if _, err := rand.Read(raw[:]); err != nil {
			return View{}, err
		}
		raw[6] = (raw[6] & 15) | 64
		raw[8] = (raw[8] & 63) | 128
		id = fmt.Sprintf("%x-%x-%x-%x-%x", raw[0:4], raw[4:6], raw[6:8], raw[8:10], raw[10:16])
	}
	args := []any{id, tenant, command.Name, command.NatureID, command.Role, command.BindingKind, command.PokemonID}
	for _, v := range command.EVs.values() {
		args = append(args, v)
	}
	for _, v := range command.IVs.values() {
		args = append(args, v)
	}
	query := `INSERT INTO poke_runtime.stat_configurations(id,tenant_id,name,nature_id,role,binding_kind,pokemon_id,ev_hp,ev_attack,ev_defense,ev_special_attack,ev_special_defense,ev_speed,iv_hp,iv_attack,iv_defense,iv_special_attack,iv_special_defense,iv_speed,is_deleted) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,false) RETURNING ` + columns
	if !create {
		query = `UPDATE poke_runtime.stat_configurations SET name=$3,nature_id=$4,role=$5,binding_kind=$6,pokemon_id=$7,ev_hp=$8,ev_attack=$9,ev_defense=$10,ev_special_attack=$11,ev_special_defense=$12,ev_speed=$13,iv_hp=$14,iv_attack=$15,iv_defense=$16,iv_special_attack=$17,iv_special_defense=$18,iv_speed=$19,updated_at=now() WHERE id=$1 AND tenant_id=$2 AND NOT is_deleted RETURNING ` + columns
	}
	view, err := scanView(store.db.QueryRowContext(ctx, query, args...))
	if errors.Is(err, sql.ErrNoRows) {
		return View{}, ErrNotFound
	}
	return view, err
}

// Delete 对 tenant 的有效配置软删除，返回 ErrNotFound 时不改变任何对象。
func (store *Store) Delete(ctx context.Context, tenant, id string) error {
	result, err := store.db.ExecContext(ctx, `UPDATE poke_runtime.stat_configurations SET is_deleted=true,updated_at=now() WHERE id=$1 AND tenant_id=$2 AND NOT is_deleted`, id, tenant)
	if err != nil {
		return err
	}
	count, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if count == 0 {
		return ErrNotFound
	}
	return nil
}

// ensureReference 在当前事务验证 ref 属于已知内置项或 tenant 的未删除对象。
func ensureReference(ctx context.Context, tx *sql.Tx, tenant string, ref Reference) error {
	if ref.Source == "builtin" {
		for _, view := range builtins() {
			if view.Key == ref.Key {
				return nil
			}
		}
		return fmt.Errorf("%w: builtin configuration not found", ErrInvalidPreference)
	}
	if ref.Source != "custom" || ref.Key == "" {
		return fmt.Errorf("%w: invalid configuration reference", ErrInvalidPreference)
	}
	var exists bool
	err := tx.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM poke_runtime.stat_configurations WHERE id=$1 AND tenant_id=$2 AND NOT is_deleted)`, ref.Key, tenant).Scan(&exists)
	if err != nil {
		return err
	}
	if !exists {
		return ErrNotFound
	}
	return nil
}

// Preferences 在一笔事务中保存已验证的 refs；排序会显式恢复显示，隐藏设置重置排序为零。
// hidden 为 nil 时采用 refs 中的位置；失败回滚整批，不保存部分偏好。
func (store *Store) Preferences(ctx context.Context, tenant, role string, refs []Reference, hidden *bool) error {
	if role != "attacker" && role != "defender" {
		return fmt.Errorf("%w: role must be attacker or defender", ErrInvalidPreference)
	}
	tx, err := store.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	seen := map[Reference]bool{}
	for index, ref := range refs {
		if seen[ref] {
			return fmt.Errorf("%w: duplicate configuration reference in order", ErrInvalidPreference)
		}
		seen[ref] = true
		if err = ensureReference(ctx, tx, tenant, ref); err != nil {
			return err
		}
		order, isHidden := index, false
		if hidden != nil {
			order = 0
			isHidden = *hidden
		}
		_, err = tx.ExecContext(ctx, `INSERT INTO poke_runtime.stat_configuration_preferences(tenant_id,role,reference_type,reference_key,sort_order,hidden) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT ON CONSTRAINT stat_configuration_preferences_ref_uq DO UPDATE SET sort_order=EXCLUDED.sort_order,hidden=EXCLUDED.hidden,updated_at=now()`, tenant, role, ref.Source, ref.Key, order, isHidden)
		if err != nil {
			return err
		}
	}
	return tx.Commit()
}
