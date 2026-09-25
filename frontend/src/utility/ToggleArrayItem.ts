export const toggleArrayItem = <T>(array: T[], item: T): T[] =>
  array.includes(item)
    ? array.filter(current => current !== item)
    : [...array, item]
