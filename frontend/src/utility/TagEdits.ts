import type { TagGroup, TagPreview } from '@/types/TagPreview'

const inGroup = (preview: TagPreview, kind: string, edit: (group: TagGroup) => TagGroup): TagPreview => ({
  ...preview,
  groups: preview.groups.map(group => (group.kind === kind ? edit(group) : group)),
})

export const toggleTag = (preview: TagPreview, kind: string, text: string): TagPreview =>
  inGroup(preview, kind, group => ({
    ...group,
    tags: group.tags.map(tag => (tag.text === text ? { ...tag, selected: !tag.selected } : tag)),
  }))

// Uno que ya esta en el grupo, sin importar mayusculas, se selecciona en vez de repetirse
export const addTag = (preview: TagPreview, kind: string, text: string): TagPreview =>
  inGroup(preview, kind, group => {
    const existing = group.tags.find(tag => tag.text.toLowerCase() === text.toLowerCase())
    const tags = existing
      ? group.tags.map(tag => (tag === existing ? { ...tag, selected: true } : tag))
      : [...group.tags, { text, source: 'you' as const, selected: true }]
    return { ...group, tags }
  })
