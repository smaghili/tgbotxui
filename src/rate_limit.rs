use std::collections::VecDeque;
use std::time::Instant;

use dashmap::DashMap;

#[derive(Clone, Default)]
pub struct SlidingWindowRateLimiter {
    buckets: DashMap<i64, VecDeque<Instant>>,
}

impl SlidingWindowRateLimiter {
    pub fn allow(&self, user_id: i64, limit: usize, window_seconds: u64) -> bool {
        let now = Instant::now();
        let mut entry = self.buckets.entry(user_id).or_default();
        while let Some(front) = entry.front() {
            if now.duration_since(*front).as_secs() > window_seconds {
                entry.pop_front();
            } else {
                break;
            }
        }
        if entry.len() >= limit {
            return false;
        }
        entry.push_back(now);
        true
    }
}
