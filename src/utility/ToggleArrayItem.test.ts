import { describe, expect, it } from 'vitest'
import { toggleArrayItem } from '@/utility/ToggleArrayItem'

describe('toggleArrayItem', () => {
  it('adds the item when it is not present', () => {
    expect(toggleArrayItem([1, 2], 3)).toEqual([1, 2, 3])
  })

  it('removes the item when it is already present', () => {
    expect(toggleArrayItem([1, 2, 3], 2)).toEqual([1, 3])
  })
})
