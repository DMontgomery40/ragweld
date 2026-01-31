// Legacy stub - index profiles concept replaced by corpus-level config
// This provides compatibility for components still referencing the old pattern

export interface IndexProfile {
  id: string;
  name: string;
  description?: string;
  chunkingStrategy: string;
  embeddingModel: string;
  chunkSize: number;
  chunkOverlap: number;
  isDefault?: boolean;
}

export const IndexProfilesService = {
  async list(): Promise<IndexProfile[]> {
    console.warn('IndexProfilesService.list is a legacy stub');
    return [];
  },

  async get(id: string): Promise<IndexProfile | null> {
    console.warn(`IndexProfilesService.get(${id}) is a legacy stub`);
    return null;
  },

  async save(profile: IndexProfile): Promise<void> {
    console.warn(`IndexProfilesService.save(${profile.id}) is a legacy stub`);
  },

  async delete(id: string): Promise<void> {
    console.warn(`IndexProfilesService.delete(${id}) is a legacy stub`);
  },

  async setDefault(id: string): Promise<void> {
    console.warn(`IndexProfilesService.setDefault(${id}) is a legacy stub`);
  },
};

export default IndexProfilesService;
