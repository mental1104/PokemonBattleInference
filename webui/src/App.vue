<template>
  <div>
    <h1>Damage Calculator</h1>
    <AttackerDefender />
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import AttackerDefender from './components/AttackerDefender.vue';

export default defineComponent({
  name: 'App',
  components: {
    AttackerDefender,
  },
});
</script>

<style>
body {
  font-family: Arial, sans-serif;
  margin: 0;
  padding: 0;
}
</style>
