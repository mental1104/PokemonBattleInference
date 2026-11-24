package httpapi

import (
	"reflect"

	"pokemonbattleinference/server/internal/jobs"
)

// matchesSubmissionRecord 保留原configuration-jobs已存在任务的比较边界：规则轴/规格/全局case数。
// existing来自真实PG快照，definition是本次已通过strict的规划；此入口的ID本身包含key/完整command/预算。
// 不比较Go私有执行格式或提交时Core版本，也不覆盖旧Definition；fixed仅key身份的逐case比较仍由其独立适配负责。
// 返回true表示可原样重放现有任务；false表示同一任务ID的原业务规格冲突，不修改任一输入。
func matchesSubmissionRecord(existing jobs.Job, definition jobs.Definition) bool {
	return existing.RulesetID == definition.RulesetID && existing.VersionGroupID == definition.VersionGroupID && existing.Revision == definition.Revision && existing.Counts.Total == len(definition.Cases) && reflect.DeepEqual(existing.Spec, definition.Spec)
}
