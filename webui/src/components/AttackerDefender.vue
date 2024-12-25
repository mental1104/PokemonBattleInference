<template>
  <div class="app-container">
    <!-- Header Section -->
    <div class="header">
      <h1>Attack vs Defense</h1>
      <p>Select attacker and defender attributes</p>
    </div>

    <!-- Main Content Section -->
    <div class="content">
      <!-- Wrapper to divide attacker and defender -->
      <div class="info-wrapper">
        <!-- Attacker Info (Left) -->
        <div class="info-section attacker">
          <h2>Attacker</h2>
          <div>
            <label for="attacker-id">Attacker ID:</label>
            <input 
              id="attacker-id" 
              v-model.number="attacker.id" 
              type="number" 
              min="1" 
              placeholder="Enter attacker ID" 
              required 
            />
          </div>
          <div>
            <label for="attacker-level">Level:</label>
            <select id="attacker-level" v-model="attacker.level">
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
          </div>
          <div>
            <label for="attacker-nature">Nature:</label>
            <input 
              id="attacker-nature" 
              v-model="attacker.nature" 
              type="text" 
              placeholder="Enter nature" 
            />
          </div>

          <!-- Attacker's Basepoint Section -->
          <div class="slider-container">
            <h3>Basepoint</h3>
            <div v-for="(label, index) in basepointLabels" :key="'attacker-basepoint-' + index" class="slider-item">
              <label :for="'attacker-basepoint-' + index">{{ label }}:</label>
              <input 
                type="range" 
                v-model.number="attacker.basepoint[index]" 
                min="0" 
                max="252" 
                :id="'attacker-basepoint-' + index" 
                class="slider"
              />
              <p class="value">{{ attacker.basepoint[index] }}</p>
            </div>
          </div>

          <!-- Attacker's Individual Values Section -->
          <div class="slider-container">
            <h3>Individual Values</h3>
            <div v-for="(label, index) in individualValueLabels" :key="'attacker-individual-value-' + index" class="slider-item">
              <label :for="'attacker-individual-value-' + index">{{ label }}:</label>
              <input 
                type="range" 
                v-model.number="attacker.individual_values[index]" 
                min="0" 
                max="31" 
                :id="'attacker-individual-value-' + index" 
                class="slider"
              />
              <p class="value">{{ attacker.individual_values[index] }}</p>
            </div>
          </div>
        </div>

        <!-- Defender Info (Right) -->
        <div class="info-section defenser">
          <h2>Defender</h2>
          <div>
            <label for="defender-id">Defender ID:</label>
            <input 
              id="defender-id" 
              v-model.number="defender.id" 
              type="number" 
              min="1" 
              placeholder="Enter defender ID" 
              required 
            />
          </div>
          <div>
            <label for="defender-level">Level:</label>
            <select id="defender-level" v-model="defender.level">
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
          </div>
          <div>
            <label for="defender-nature">Nature:</label>
            <input 
              id="defender-nature" 
              v-model="defender.nature" 
              type="text" 
              placeholder="Enter nature" 
            />
          </div>

          <!-- Defender's Basepoint Section -->
          <div class="slider-container">
            <h3>Basepoint</h3>
            <div v-for="(label, index) in basepointLabels" :key="'defender-basepoint-' + index" class="slider-item">
              <label :for="'defender-basepoint-' + index">{{ label }}:</label>
              <input 
                type="range" 
                v-model.number="defender.basepoint[index]" 
                min="0" 
                max="252" 
                :id="'defender-basepoint-' + index" 
                class="slider"
              />
              <p class="value">{{ defender.basepoint[index] }}</p>
            </div>
          </div>

          <!-- Defender's Individual Values Section -->
          <div class="slider-container">
            <h3>Individual Values</h3>
            <div v-for="(label, index) in individualValueLabels" :key="'defender-individual-value-' + index" class="slider-item">
              <label :for="'defender-individual-value-' + index">{{ label }}:</label>
              <input 
                type="range" 
                v-model.number="defender.individual_values[index]" 
                min="0" 
                max="31" 
                :id="'defender-individual-value-' + index" 
                class="slider"
              />
              <p class="value">{{ defender.individual_values[index] }}</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Move Info Section -->
      <div class="move-section">
        <h2>Move</h2>
        <div>
          <label for="move-power">Power:</label>
          <input 
            id="move-power" 
            v-model.number="move.power" 
            type="number" 
            min="1" 
            max="250" 
          />
        </div>
        <div>
          <label for="move-type">Move Type:</label>
          <input 
            id="move-type" 
            v-model="move.move_type" 
            type="text" 
            placeholder="Enter move type" 
          />
        </div>
        <div>
          <label for="move-element">Move Element:</label>
          <input 
            id="move-element" 
            v-model="move.type" 
            type="text" 
            placeholder="Enter move element" 
          />
        </div>
      </div>

      <!-- Submit Button -->
      <div>
        <button @click="sendRequest">Send Request</button>
      </div>

      <!-- Results Section -->
      <div v-if="result">
        <h2>Results</h2>
        <p><strong>Formula:</strong> {{ result.formula }}</p>
        <p><strong>Min Damage:</strong> {{ result.min_damage }}</p>
        <p><strong>Max Damage:</strong> {{ result.max_damage }}</p>
        <p><strong>Random Damage:</strong> {{ result.random_damage }}</p>
        <p><strong>Min Damage Percent:</strong> {{ result.min_damage_percent }}%</p>
        <p><strong>Max Damage Percent:</strong> {{ result.max_damage_percent }}%</p>
        <p><strong>Random Damage Percent:</strong> {{ result.random_damage_percent }}%</p>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  data() {
    return {
      attacker: {
        id: 727,
        level: 50,
        basepoint: [236, 4, 100, 0, 156, 12],
        individual_values: [31, 31, 31, 31, 31, 31],
        nature: "Careful"
      },
      defender: {
        id: 591,
        level: 50,
        basepoint: [244, 0, 236, 4, 20, 4],
        individual_values: [31, 31, 31, 31, 31, 31],
        nature: "Bold"
      },
      move: {
        power: 120,
        move_type: "physical_move",
        type: "Fire"
      },
      basepointLabels: ['HP', '攻击', '防御', '特攻', '特防', '速度'],
      individualValueLabels: ['HP', '攻击', '防御', '特攻', '特防', '速度'],
      result: null
    };
  },
  methods: {
    async sendRequest() {
      const requestBody = {
        attacker: {
          id: this.attacker.id,
          level: this.attacker.level,
          basepoint: this.attacker.basepoint,
          individual_values: this.attacker.individual_values,
          nature: this.attacker.nature
        },
        defenser: {
          id: this.defender.id,
          level: this.defender.level,
          basepoint: this.defender.basepoint,
          individual_values: this.defender.individual_values,
          nature: this.defender.nature
        },
        move: {
          power: this.move.power,
          move_type: this.move.move_type,
          type: this.move.type
        }
      };

      try {
        const response = await fetch('http://localhost:8001/nexus/api/damage', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(requestBody)
        });
        this.result = await response.json();
      } catch (error) {
        console.error("Error:", error);
      }
    }
  }
};
</script>

<style scoped>
.app-container {
  padding: 20px;
}

.header {
  text-align: center;
}

.content {
  margin-top: 20px;
}

.info-wrapper {
  display: flex;
  justify-content: space-between;
}

.info-section {
  width: 45%;
}

.attacker {
  text-align: left;
}

.defenser {
  text-align: right;
}

.slider-container {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 20px;
}

.slider-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.slider {
  flex-grow: 1;
}

.value {
  margin-left: 10px;
}

button {
  margin-top: 20px;
  padding: 10px;
  font-size: 16px;
  cursor: pointer;
}

.results {
  margin-top: 30px;
}
</style>
