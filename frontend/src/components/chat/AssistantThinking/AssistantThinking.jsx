import { useMemo, useState } from 'react';

import styles from './AssistantThinking.module.css';

function normalizeItems(items = []) {
  return items
    .map((item) => {
      if (typeof item === 'string') {
        return { label: item, displayValue: '' };
      }
      return {
        label: String(item?.label || '').trim(),
        displayValue: String(item?.display_value || item?.displayValue || '').trim(),
      };
    })
    .filter((item) => item.label);
}

function ItemRows({ items }) {
  return (
    <div className={styles.itemRows}>
      {items.map((item) => (
        <div key={`${item.label}-${item.displayValue}`}>
          <span>{item.label}</span>
          {item.displayValue && <strong>{item.displayValue}</strong>}
        </div>
      ))}
    </div>
  );
}

function AssistantThinking({ progress = null, fallbackItems = [] }) {
  const [isOpen, setIsOpen] = useState(false);
  const confirmedItems = useMemo(
    () => normalizeItems(progress?.confirmed_items || []),
    [progress],
  );
  const unresolvedItems = useMemo(
    () => normalizeItems(progress?.unresolved_items || []),
    [progress],
  );
  const remainingItems = useMemo(() => {
    const sourceItems = [
      ...(progress?.conflict_items || []),
      ...(progress?.remaining_items || []),
    ];
    return normalizeItems(sourceItems.length ? sourceItems : fallbackItems);
  }, [fallbackItems, progress]);

  return (
    <div className={styles.thinkingRow} role="status" aria-live="polite">
      <span className={styles.avatar} aria-hidden="true">
        <img src="/images/thinking.png" alt="" />
      </span>

      <div className={`${styles.bubble} ${isOpen ? styles.bubbleOpen : styles.bubbleClosed}`}>
        <button
          type="button"
          className={styles.toggleButton}
          onClick={() => setIsOpen((current) => !current)}
          aria-expanded={isOpen}
        >
          <span>생각 중</span>
          <i aria-hidden="true" />
        </button>

        {isOpen && (
          <div className={styles.details}>
            <h3>계약 전 확인 중</h3>

            <section>
              <strong>현재 확인된 정보</strong>
              {confirmedItems.length ? (
                <ItemRows items={confirmedItems} />
              ) : (
                <p>아직 확인된 정보가 없습니다.</p>
              )}
            </section>

            {unresolvedItems.length > 0 && (
              <section>
                <strong>확인하지 못한 정보</strong>
                <ItemRows items={unresolvedItems} />
              </section>
            )}

            <section>
              <strong>남은 확인 항목 {remainingItems.length}개</strong>
              {remainingItems.length ? (
                <ItemRows items={remainingItems} />
              ) : (
                <p>모든 질문에 답했습니다.</p>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

export default AssistantThinking;
