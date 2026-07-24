import rawFixture from './contracts/one_on_one_move_pool.v1.json';
import type { OneOnOneContractFixture } from '../types/oneOnOneConfigurationSpace';

/** Python application 与前端并行分支共同消费的版本化合同 fixture。 */
export const oneOnOneConfigurationContractFixture = rawFixture as OneOnOneContractFixture;
