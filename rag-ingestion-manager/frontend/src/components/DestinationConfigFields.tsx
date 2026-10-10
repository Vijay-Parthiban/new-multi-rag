import type { KnowledgeDestinationOption, LiteLLMModelOption } from "../api"
import ConfigFields from "./ConfigFields"

type DestinationConfigFieldsProps = {
  option: KnowledgeDestinationOption
  config: Record<string, unknown>
  litellmModels: LiteLLMModelOption[]
  onChange: (nextConfig: Record<string, unknown>) => void
}

/**
 * The settings of one destination type, rendered from the spec the options route
 * supplies. The field rendering itself lives in ``ConfigFields``, which the chunk
 * settings share.
 */
export default function DestinationConfigFields({
  option,
  config,
  litellmModels,
  onChange,
}: DestinationConfigFieldsProps) {
  return (
    <ConfigFields
      fields={option.fields || []}
      values={config}
      models={litellmModels}
      onChange={onChange}
      idPrefix={option.id}
    />
  )
}
