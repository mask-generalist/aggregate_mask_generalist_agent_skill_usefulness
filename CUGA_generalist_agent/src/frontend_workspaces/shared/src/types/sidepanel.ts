export interface Field {
  field_name: string;
  field_description?: string;
  field_value?: any;
  isMultiSelect?: boolean;
  field_type: string;
  required: boolean;
}
