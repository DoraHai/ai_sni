// Preconditions are captured when the user reads the draft. Never fetch a new
// version behind an old edit, or silently turn an update into a creation.
export function requireImageVersion(value) {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) {
    throw new Error('图片审核版本缺失，请刷新并重新核对后提交')
  }
  return value
}

export function imageReviewPrecondition(review) {
  if (review == null) return { expected_review_id: null, expected_review_version: null }
  if (!Number.isSafeInteger(review.id) || review.id <= 0) {
    throw new Error('图片审核记录无效，请刷新后重试')
  }
  return { expected_review_id: review.id, expected_review_version: requireImageVersion(review.version) }
}
