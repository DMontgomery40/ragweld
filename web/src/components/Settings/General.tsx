// TriBrid - Settings/General
//
// This wrapper preserves the Settings tab layout while we migrate
// all configuration onto TriBridConfig (Pydantic-first).

import { GeneralSubtab } from '@/components/Admin/GeneralSubtab';

export function General() {
  return <GeneralSubtab />;
}

export default General;

