// Package configurations 保留原租户预设、快照和显示偏好的 HTTP 合同。
package configurations

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"
)

// Spread 保存六项投入；字段顺序不影响规范化快照编码。
type Spread struct {
	HP             int `json:"hp"`
	Attack         int `json:"attack"`
	Defense        int `json:"defense"`
	SpecialAttack  int `json:"special_attack"`
	SpecialDefense int `json:"special_defense"`
	Speed          int `json:"speed"`
}

// UnmarshalJSON 校验 data 的六个整数字段都存在，错误时不修改接收者。
func (spread *Spread) UnmarshalJSON(data []byte) error {
	var raw struct {
		HP             *int `json:"hp"`
		Attack         *int `json:"attack"`
		Defense        *int `json:"defense"`
		SpecialAttack  *int `json:"special_attack"`
		SpecialDefense *int `json:"special_defense"`
		Speed          *int `json:"speed"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}
	if raw.HP == nil || raw.Attack == nil || raw.Defense == nil || raw.SpecialAttack == nil || raw.SpecialDefense == nil || raw.Speed == nil {
		return errors.New("all six stat fields are required")
	}
	*spread = Spread{*raw.HP, *raw.Attack, *raw.Defense, *raw.SpecialAttack, *raw.SpecialDefense, *raw.Speed}
	return nil
}

// values 返回能力顺序固定的副本，供统一范围检查和 SQL 参数绑定使用。
func (spread Spread) values() []int {
	return []int{spread.HP, spread.Attack, spread.Defense, spread.SpecialAttack, spread.SpecialDefense, spread.Speed}
}

// Command 是完整保存请求；IVs 缺省为 6V，显式 null 也沿用旧默认。
type Command struct {
	Name        string  `json:"name"`
	NatureID    string  `json:"nature_id"`
	EVs         *Spread `json:"evs"`
	IVs         *Spread `json:"ivs"`
	Role        string  `json:"role"`
	BindingKind string  `json:"binding_kind"`
	PokemonID   *int    `json:"pokemon_id"`
}

// Validate 规范化 command 的名字和缺省 IV，并拒绝非法性格、绑定和投入。
func (command *Command) Validate() error {
	command.Name = strings.TrimSpace(command.Name)
	if n := utf8.RuneCountInString(command.Name); n < 1 || n > 48 {
		return errors.New("configuration name must contain 1 to 48 characters")
	}
	if !knownNature(command.NatureID) {
		return errors.New("unsupported nature")
	}
	if command.Role != "attacker" && command.Role != "defender" && command.Role != "both" {
		return errors.New("invalid role")
	}
	if command.BindingKind == "global" {
		if command.PokemonID != nil {
			return errors.New("global configuration must not bind pokemon_id")
		}
	} else if command.BindingKind != "pokemon" || command.PokemonID == nil || *command.PokemonID <= 0 {
		return errors.New("pokemon binding requires positive pokemon_id")
	}
	if command.EVs == nil {
		return errors.New("evs are required")
	}
	if command.IVs == nil {
		command.IVs = &Spread{31, 31, 31, 31, 31, 31}
	}
	total := 0
	for _, value := range command.EVs.values() {
		if value < 0 || value > 252 {
			return errors.New("EV must be between 0 and 252")
		}
		total += value
	}
	if total > 510 {
		return errors.New("EV total must not exceed 510")
	}
	for _, value := range command.IVs.values() {
		if value < 0 || value > 31 {
			return errors.New("IV must be between 0 and 31")
		}
	}
	return nil
}

// Reference 使用 source 和 key 区分内置定义与租户自定义对象。
type Reference struct {
	Source string `json:"source"`
	Key    string `json:"key"`
}

// View 是原配置 API 的完整读取模型，删除采用软删除保留历史快照。
type View struct {
	ID                string     `json:"id"`
	Source            string     `json:"source"`
	Key               string     `json:"key"`
	Name              string     `json:"name"`
	NatureID          string     `json:"nature_id"`
	EVs               Spread     `json:"evs"`
	IVs               Spread     `json:"ivs"`
	Role              string     `json:"role"`
	BindingKind       string     `json:"binding_kind"`
	PokemonID         *int       `json:"pokemon_id"`
	Description       string     `json:"description"`
	Hidden            bool       `json:"hidden"`
	Visible           bool       `json:"visible"`
	SortOrder         int        `json:"sort_order"`
	Editable          bool       `json:"editable"`
	Renamable         bool       `json:"renamable"`
	Deletable         bool       `json:"deletable"`
	Hideable          bool       `json:"hideable"`
	SnapshotProfileID string     `json:"snapshot_profile_id"`
	UpdatedAt         *time.Time `json:"updated_at"`
}

// finalize 返回补齐权限和不可变快照的 view；编码仅使用确定存在的标量。
func finalize(view View) View {
	view.ID = view.Source + ":" + view.Key
	view.Visible = !view.Hidden
	view.Hideable = true
	view.Editable = view.Source == "custom"
	view.Renamable = view.Editable
	view.Deletable = view.Editable
	payload := map[string]any{"nature_id": view.NatureID, "evs": spreadMap(view.EVs), "ivs": spreadMap(view.IVs), "label": view.Name, "source": view.Source, "key": view.Key}
	var data bytes.Buffer
	encoder := json.NewEncoder(&data)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(payload); err != nil {
		panic(fmt.Sprintf("snapshot scalar encoding failed: %v", err))
	}
	view.SnapshotProfileID = "preset-snapshot:" + base64.RawURLEncoding.EncodeToString(bytes.TrimSuffix(data.Bytes(), []byte("\n")))
	return view
}

// spreadMap 返回键排序由 encoding/json 确定的快照对象，匹配旧 Python 合同。
func spreadMap(spread Spread) map[string]int {
	return map[string]int{"hp": spread.HP, "attack": spread.Attack, "defense": spread.Defense, "special_attack": spread.SpecialAttack, "special_defense": spread.SpecialDefense, "speed": spread.Speed}
}

// Nature 保留原接口的性格标签和增减能力字段。
type Nature struct {
	Identifier    string  `json:"identifier"`
	Label         string  `json:"label"`
	IncreasedStat *string `json:"increased_stat"`
	DecreasedStat *string `json:"decreased_stat"`
}

// Natures 返回旧领域定义的 25 种性格；调用者得到独立切片。
func Natures() []Nature {
	definitions := [][3]string{{"hardy", "", ""}, {"lonely", "attack", "defense"}, {"brave", "attack", "speed"}, {"adamant", "attack", "special_attack"}, {"naughty", "attack", "special_defense"}, {"bold", "defense", "attack"}, {"docile", "", ""}, {"relaxed", "defense", "speed"}, {"impish", "defense", "special_attack"}, {"lax", "defense", "special_defense"}, {"timid", "speed", "attack"}, {"hasty", "speed", "defense"}, {"serious", "", ""}, {"jolly", "speed", "special_attack"}, {"naive", "speed", "special_defense"}, {"modest", "special_attack", "attack"}, {"mild", "special_attack", "defense"}, {"quiet", "special_attack", "speed"}, {"bashful", "", ""}, {"rash", "special_attack", "special_defense"}, {"calm", "special_defense", "attack"}, {"gentle", "special_defense", "defense"}, {"sassy", "special_defense", "speed"}, {"careful", "special_defense", "special_attack"}, {"quirky", "", ""}}
	result := make([]Nature, 0, len(definitions))
	for _, item := range definitions {
		nature := Nature{Identifier: item[0], Label: strings.ToUpper(item[0][:1]) + item[0][1:]}
		if item[1] != "" {
			inc, dec := item[1], item[2]
			nature.IncreasedStat = &inc
			nature.DecreasedStat = &dec
		}
		result = append(result, nature)
	}
	return result
}

// knownNature 判断 identifier 是否属于同一静态合同，拒绝未知规则。
func knownNature(identifier string) bool {
	for _, nature := range Natures() {
		if nature.Identifier == identifier {
			return true
		}
	}
	return false
}

// builtins 返回保持旧插入顺序和原文案的七个预设。
func builtins() []View {
	result := []View{
		{Key: "no_investment", Name: "无投入", NatureID: "hardy", Role: "both", Description: "0 EV、6V、中性性格，适合做无投入基线。"},
		{Key: "max_atk_plus", Name: "极限物攻", NatureID: "adamant", EVs: Spread{Attack: 252}, Role: "attacker", Description: "252 Attack EV、攻击性格，用于物理攻击方上限。"},
		{Key: "max_spatk_plus", Name: "极限特攻", NatureID: "modest", EVs: Spread{SpecialAttack: 252}, Role: "attacker", Description: "252 Special Attack EV、特攻性格，用于特殊攻击方上限。"},
		{Key: "max_speed_plus", Name: "极限速度", NatureID: "jolly", EVs: Spread{Speed: 252}, Role: "both", Description: "252 Speed EV、速度性格，用于速度线比较。"},
		{Key: "max_hp", Name: "满 HP", NatureID: "hardy", EVs: Spread{HP: 252}, Role: "defender", Description: "252 HP EV、中性性格，用于基础耐久线。"},
		{Key: "max_hp_def_plus", Name: "极限物耐", NatureID: "bold", EVs: Spread{HP: 252, Defense: 252}, Role: "defender", Description: "252 HP / 252 Defense EV、防御性格。"},
		{Key: "max_hp_spdef_plus", Name: "极限特耐", NatureID: "calm", EVs: Spread{HP: 252, SpecialDefense: 252}, Role: "defender", Description: "252 HP / 252 Special Defense EV、特防性格。"},
	}
	for i := range result {
		result[i].Source = "builtin"
		result[i].BindingKind = "global"
		result[i].IVs = Spread{31, 31, 31, 31, 31, 31}
		result[i].SortOrder = 1000 + i
	}
	return result
}
