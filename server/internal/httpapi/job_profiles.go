package httpapi

import (
	"encoding/base64"
	"encoding/json"
	"pokemonbattleinference/server/internal/jobs"
	"strings"
)

// jobProfiles 保留原 inference 的七项 PRESETS 与不可变 snapshot，不扩大成静态 calculator 的十项集合。
// selections 顺序为 attacker/defender；遇到原准备错误只返回冻结失败事实，不构造能力或战斗输入。
func jobProfiles(selections []jobSelection) ([]calculatorProfile, *jobs.PreparationFailure) {
	profiles := make([]calculatorProfile, 0, len(selections))
	for _, selection := range selections {
		key := selection.Fixed.Profile
		known := false
		switch key {
		case "max_atk_plus", "max_atk_neutral", "max_hp", "max_hp_def", "max_hp_def_plus", "max_hp_spdef", "max_hp_spdef_plus":
			known = true
		}
		if !known && !strings.HasPrefix(key, "preset-snapshot:") {
			return nil, &jobs.PreparationFailure{Code: "invalid_configuration", Diagnostic: "ConfigurationSpaceError: unknown stat profile preset: " + key}
		}
		profile, err := readCalculatorProfile(key)
		if err != nil {
			// snapshot 的数值约束在旧 provider 中包装为 ConfigurationSpaceError；能力公式仍只交 Core。
			message := err.Error()
			switch message {
			case "unsupported nature":
				// 旧 snapshot 诊断包含原性格ID；只恢复错误事实，不修改输入后继续计算。
				body, _ := base64.RawURLEncoding.DecodeString(strings.TrimRight(strings.TrimPrefix(key, "preset-snapshot:"), "="))
				var snapshot struct {
					Nature string `json:"nature_id"`
				}
				_ = json.Unmarshal(body, &snapshot)
				message = "unsupported nature: " + snapshot.Nature
			case "EV must be between 0 and 252":
				message = "each EV value must be between 0 and 252"
			case "EV total must not exceed 510":
				message = "total EVs must not exceed 510"
			case "IV must be between 0 and 31":
				message = "each IV value must be between 0 and 31"
			}
			return nil, &jobs.PreparationFailure{Code: "invalid_configuration", Diagnostic: "ConfigurationSpaceError: " + message}
		}
		profiles = append(profiles, profile)
	}
	return profiles, nil
}
