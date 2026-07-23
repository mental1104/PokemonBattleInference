<script setup lang="ts">
import { ref, watch } from 'vue';
import type { CalculateDamageResponse } from '../api/calculator';

const props = defineProps<{
  result: CalculateDamageResponse | null;
  stale: boolean;
}>();

const failedSprites = ref<Set<string>>(new Set());

/** 把概率转换成一位小数百分比文本。 */
function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/** 新结果进入页面时清空失败缓存，让双方图片按新 URL 重新尝试加载。 */
watch(
  () => props.result,
  () => {
    failedSprites.value = new Set();
  },
);

/** 标记某个结果图片加载失败；这只影响展示，不阻断伤害结果。 */
function markSpriteFailed(key: string): void {
  failedSprites.value = new Set([...failedSprites.value, key]);
}
</script>

<template>
  <section class="result-band">
    <div class="result-header">
      <h2>伤害结果</h2>
      <span v-if="stale" class="stale-badge">已过期</span>
    </div>
    <div v-if="!result" class="muted">选择攻击方、招式、防守方和配置模板后计算。</div>
    <template v-else>
      <div class="metric-grid">
        <div class="metric">
          <span>伤害</span>
          <strong>{{ result.damage.min }}-{{ result.damage.max }}</strong>
          <small>{{ result.damage.min_percent.toFixed(1) }}%-{{ result.damage.max_percent.toFixed(1) }}%</small>
        </div>
        <div class="metric">
          <span>OHKO</span>
          <strong>{{ percent(result.ko.ohko_probability) }}</strong>
          <small>{{ result.ko.guaranteed_ohko ? '稳定一击' : '非稳定一击' }}</small>
        </div>
        <div class="metric">
          <span>2HKO</span>
          <strong>{{ percent(result.ko.two_hit_ko_probability) }}</strong>
          <small>{{ result.ko.guaranteed_2hko ? '稳定二击' : '概率二击' }}</small>
        </div>
      </div>
      <div class="result-details">
        <div>
          <img
            v-if="!failedSprites.has('attacker')"
            class="result-sprite"
            :src="result.attacker.sprite_url"
            :alt="result.attacker.display_name"
            loading="lazy"
            @error="markSpriteFailed('attacker')"
          />
          <strong>{{ result.attacker.display_name }}</strong>
          <span class="muted">Atk/SpA {{ result.attacker.effective_attack }}</span>
        </div>
        <div>
          <img
            v-if="!failedSprites.has('defender')"
            class="result-sprite"
            :src="result.defender.sprite_url"
            :alt="result.defender.display_name"
            loading="lazy"
            @error="markSpriteFailed('defender')"
          />
          <strong>{{ result.defender.display_name }}</strong>
          <span class="muted">HP {{ result.defender.effective_hp }} · Def/SpD {{ result.defender.effective_defense }}</span>
        </div>
        <div>
          <strong>{{ result.move.display_name }}</strong>
          <span class="muted">{{ result.move.type_name }} · {{ result.move.category }} · {{ result.move.power }}</span>
        </div>
      </div>
      <details class="detail-box">
        <summary>查看明细</summary>
        <div class="rolls">{{ result.damage.rolls.join(', ') }}</div>
        <ul>
          <li v-for="modifier in result.modifiers" :key="modifier.key">
            {{ modifier.key }} · {{ modifier.multiplier ?? `${modifier.min_multiplier}-${modifier.max_multiplier}` }}
          </li>
        </ul>
      </details>
    </template>
  </section>
</template>
