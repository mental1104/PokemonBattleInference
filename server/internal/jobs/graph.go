package jobs

import (
	"context"
	"errors"
)

// ErrExecutionSpecNotFound 表示旧任务父行存在，但没有按需重建所需的原冻结执行规格。
// 这不是Go definition缺失；旧Python任务不要求具有Go私有定义。
var ErrExecutionSpecNotFound = errors.New("battle inference execution spec not found")

// GraphJob 读取按需完整图所需的原任务/规格，并保留原先查job再查execution spec的404分类。
// ctx取消所有SQL；id为公开任务身份。成功返回独立快照，不更改任务、租约、结果或定义。
func (store *Store) GraphJob(ctx context.Context, id string) (Job, error) {
	job, err := store.Get(ctx, id)
	if !errors.Is(err, ErrNotFound) {
		return job, err
	}
	// Get的INNER JOIN不能区分这两种旧库情况；只在未找到时补查原父行/进度，不读私有定义。
	var exists bool
	if err = store.db.QueryRowContext(ctx, `SELECT EXISTS(SELECT 1 FROM poke_runtime.battle_inference_jobs j JOIN poke_runtime.battle_inference_job_progress p ON p.job_id=j.job_id WHERE j.job_id=$1)`, id).Scan(&exists); err != nil {
		return Job{}, err
	}
	if exists {
		return Job{}, ErrExecutionSpecNotFound
	}
	return Job{}, ErrNotFound
}
