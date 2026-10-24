import { useRef, useState } from "react";
import { pullDistance, pullStage, shouldRefreshOnRelease } from "../feedLogic";

export function usePullToRefresh(refreshing: boolean, onRefresh: () => void) {
  const pullDistanceRef = useRef(0);
  const pullIndicatorRef = useRef<HTMLDivElement>(null);
  const pullSpinnerRef = useRef<HTMLDivElement>(null);
  const [stage, setStage] = useState(0);
  const [touchStartY, setTouchStartY] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);

  const onTouchStart = (e: React.TouchEvent) => {
    setTouchStartY(e.touches[0].clientY);
    const target = e.currentTarget as HTMLElement;
    setScrollTop(target.scrollTop || 0);
  };

  const onTouchMove = (e: React.TouchEvent) => {
    const distance = pullDistance(scrollTop, touchStartY, e.touches[0].clientY);
    if (distance === null) return;
    pullDistanceRef.current = distance;

    const ind = pullIndicatorRef.current;
    if (ind) {
      ind.style.transform = `translateY(${Math.min(distance * 0.5, 60)}px)`;
      ind.style.opacity = String(Math.min(distance / 40, 1));
    }
    const sp = pullSpinnerRef.current;
    if (sp) sp.style.transform = `rotate(${(Math.min(Math.round((distance / 80) * 100), 100) / 100) * 360}deg)`;

    const newStage = pullStage(distance);
    setStage(s => s !== newStage ? newStage : s);
  };

  const onTouchEnd = () => {
    const dist = pullDistanceRef.current;
    pullDistanceRef.current = 0;
    setStage(0);
    if (shouldRefreshOnRelease(dist, refreshing)) onRefresh();
  };

  return { pullStage: stage, pullIndicatorRef, pullSpinnerRef, touchHandlers: { onTouchStart, onTouchMove, onTouchEnd } };
}
