export { Badge, ConfidenceBadge } from "./badge";
export type {
  BadgeProps,
  BadgeVariant,
  ConfidenceBadgeProps,
  ConfidenceLevel,
} from "./badge";
export { Button } from "./button";
export type { ButtonProps, ButtonSize, ButtonVariant } from "./button";
export { FilterChip, InputChip, StatusChip } from "./chip";
export type {
  FilterChipProps,
  InputChipProps,
  StatusChipProps,
  StatusChipVariant,
} from "./chip";
export { DestinationCard } from "./destination-card";
export type { DestinationCardProps } from "./destination-card";
export { HealthBar } from "./health-bar";
export type { HealthBarProps } from "./health-bar";
export { PrimaryNavigation } from "./primary-navigation";
export type {
  NavigationDestination,
  PrimaryNavigationProps,
} from "./primary-navigation";
export { ProgressBar, RealEstimatedProgressBar } from "./progress-bar";
export type {
  ProgressBarProps,
  RealEstimatedProgressBarProps,
} from "./progress-bar";
export { RecommendationCard } from "./recommendation-card";
export type {
  RecommendationCardProps,
  RecommendationConfidenceLevel,
} from "./recommendation-card";

/* #413-A — Card, Dialog, Popover surface compositions */
export {
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  CardMeta,
  CardTitle,
  InteractiveCard,
} from "./card";
export type {
  CardBodyProps,
  CardFooterProps,
  CardHeaderProps,
  CardMetaProps,
  CardProps,
  CardTitleProps,
  InteractiveCardProps,
} from "./card";
export {
  ConfirmDialog,
  Dialog,
  DialogActions,
  DialogBody,
  DialogClose,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./dialog";
export type {
  ConfirmDialogProps,
  DialogActionsProps,
  DialogBodyProps,
  DialogCloseProps,
  DialogDescriptionProps,
  DialogFooterProps,
  DialogHeaderProps,
  DialogProps,
  DialogTitleProps,
} from "./dialog";
export {
  Popover,
  PopoverContent,
  PopoverTrigger,
  UnavailableKpiPopover,
} from "./popover";
export type {
  PopoverContentProps,
  PopoverProps,
  PopoverTriggerProps,
  UnavailableKpiPopoverProps,
} from "./popover";

/* #413-B — Form and Table surface compositions */
export {
  Form,
  FormActions,
  FormError,
  FormField,
  FormInput,
  FormLabel,
  FormSubmit,
  OtpField,
  PasswordField,
  TextField,
} from "./form";
export type {
  FormActionsProps,
  FormErrorProps,
  FormFieldProps,
  FormInputProps,
  FormLabelProps,
  FormProps,
  FormSubmitProps,
  OtpFieldProps,
  PasswordFieldProps,
  TextFieldProps,
} from "./form";
export {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "./table";
export type {
  SortDirection,
  TableBodyProps,
  TableCaptionProps,
  TableCellProps,
  TableEmptyProps,
  TableHeadProps,
  TableHeaderCellProps,
  TableProps,
  TableRowProps,
} from "./table";
/* #414-A */
export {
  LoadingIndicator,
  LoadingSkeleton,
  LoadingSpinner,
} from "./loading-indicator";
export type {
  LoadingIndicatorProps,
  LoadingIndicatorVariant,
  LoadingSkeletonProps,
  LoadingSpinnerProps,
  LoadingSpinnerSize,
} from "./loading-indicator";
export { Toast, ToastViewport } from "./toast";
export type {
  ToastAction,
  ToastItem,
  ToastProps,
  ToastVariant,
  ToastViewportItem,
  ToastViewportProps,
} from "./toast";

/* #414-B */
export {
  CHART_SERIES_COLORS,
  ChartExpandableTile,
  ChartTextEquivalent,
  MetricSparkline,
  TrendAreaChart,
  TrendLineChart,
} from "./chart";
export type {
  ChartExpandableTileProps,
  ChartTextEquivalentProps,
  ChartTrend,
  MetricSparklineProps,
  TrendAreaChartProps,
  TrendLineChartProps,
} from "./chart";
export { isNavTabActive } from "./navigation-utils";
export { PageHeader } from "./page-header";
export type { PageHeaderProps } from "./page-header";
