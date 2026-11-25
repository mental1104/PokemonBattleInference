package nativeworker

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"pokemonbattleinference/server/internal/jobs"
	"strings"
)

// executionMetadata记录传给独立子进程的最终请求摘要，以及其实际返回的版本。
// input是同一请求已验证的操作/视角；request是传给workerprocess的原始字节；response可为空或错误响应。
// 返回独立拥有的溯源值；没有合法真实版本信封时保持两版本为nil，不从协调器配置或提交资料推断。
func executionMetadata(input calculationInput, request, response []byte) jobs.ExecutionMetadata {
	digest := sha256.Sum256(request)
	metadata := jobs.ExecutionMetadata{SchemaVersion: 1, InputSchemaVersion: 1,
		InputSHA256: hex.EncodeToString(digest[:]), Operation: input.Kind, Observer: input.Observer}
	var envelope struct {
		Schema int    `json:"schema_version"`
		Engine string `json:"engine_version"`
		Rules  string `json:"rules_version"`
	}
	// 崩溃、取消或协议失败可没有真实信封；输入摘要仍有意义，不能把期望版本写成实际版本。
	if json.Unmarshal(response, &envelope) != nil || envelope.Schema != 1 || envelope.Engine == "" || envelope.Rules == "" ||
		envelope.Engine != strings.TrimSpace(envelope.Engine) || envelope.Rules != strings.TrimSpace(envelope.Rules) {
		return metadata
	}
	metadata.EngineVersion, metadata.RulesVersion = &envelope.Engine, &envelope.Rules
	return metadata
}
