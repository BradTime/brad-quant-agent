import { StrategyComingSoon } from '../coming-soon';

// 策略详情后端为 Phase 4 占位（404/501），统一展示占位页，避免调用必失败的接口。
export default function StrategyDetailPage() {
  return <StrategyComingSoon />;
}
