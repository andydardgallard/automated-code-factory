---
name: roblox-engine-api
description: Scoped INDEX of the Roblox Engine API reference (create.roblox.com/docs/reference/engine) — the section inventory (646 classes, 49 data types, 518 enums, 50 globals, 11 libraries) plus the complete A-Z class name list, and an explicit statement of what this single-page fetch does NOT contain (any class member, property, method, event, callback, enum item, data type or library signature).
---

# Roblox Engine API — index (scoped)

## Overview

The Roblox Engine API reference documents every class, data type, enumeration, function, event,
callback and property available when building on Roblox. Its landing page is an **index**: it names
the sections, gives their counts, and lists every class name letter by letter. The per-class pages
behind those names are separate documents.

| Fact | Value |
|------|------|
| Source | `https://create.roblox.com/docs/reference/engine` (the index page only) |
| Content hash of the fetched page | `839f9965e2401bee6c01ca0b15f6b1c06dd129e3785c94fbeca71ae2af461c1f` |
| Fetch kind | `http_doc` — ONE page |
| Page copyright | ©2026 Roblox Corporation — section counts and class names summarised as reference, see `NOTICE.md` |

**Single-page limitation.** The engine reference is a multi-page tree. This skill was generated
from exactly one fetched document, the index, so it can tell you *that* a class exists and *what it
is called* — it cannot tell you what that class contains. Nothing in this skill was invented to fill
that gap. Fetching the missing pages is out of scope for the generation that produced this skill.

## Key concepts

The index page declares five sections:

| Section | Count | What it holds |
|---------|-------|---------------|
| Classes | 646 | core objects and services of the engine; each has properties, methods, events and callbacks |
| Data types | 49 | value types used by class members |
| Enums | 518 | enumerations used by class members |
| Globals | 50 | global functions and values |
| Libraries | 11 | engine libraries |

The page also links **Release notes**, and it offers two machine-readable entry points:
`https://create.roblox.com/docs/reference/engine/llms.txt` (Engine API index) and
`https://create.roblox.com/docs/llms.txt` (whole documentation index). Appending `.md` to any
Creator Hub URL returns the Markdown form of that page.

Class names are grouped by first letter, and the index states the count per letter:

| Letter | Count | Letter | Count | Letter | Count |
|--------|-------|--------|-------|--------|-------|
| A | 67 | J | 2 | S | 84 |
| B | 37 | K | 5 | T | 48 |
| C | 57 | L | 15 | U | 28 |
| D | 31 | M | 29 | V | 24 |
| E | 9 | N | 10 | W | 13 |
| F | 20 | O | 6 | | |
| G | 23 | P | 60 | | |
| H | 21 | R | 37 | | |
| I | 20 | | | | |

67 + 37 + 57 + 31 + 9 + 20 + 23 + 21 + 20 + 2 + 5 + 15 + 29 + 10 + 6 + 60 + 37 + 84 + 48 + 28 +
24 + 13 = 646, which matches the declared total. There is no `Q`, `X`, `Y` or `Z` group.

## What this skill covers — and what it does not

**Covered (from the fetched index):**

- the five sections and their counts (classes 646, data types 49, enums 518, globals 50,
  libraries 11);
- the **complete list of all 646 class names**, grouped by first letter with the per-letter counts;
- the existence of the Release notes entry and of the `llms.txt` index endpoints.

**Not covered (never fetched, therefore unknown here):**

- any class's properties, methods, events, callbacks or inheritance;
- any enum's items, any data type's API, any global function signature, any library's members;
- deprecation and security markers, code samples, parameter types, default values;
- release notes, tutorials, recipes and the Cloud API or scripting guides;
- anything on a per-class page such as
  `https://create.roblox.com/docs/reference/engine/classes/<Class>`.

If a decision needs a member-level fact, this skill is the wrong tool: fetch that page from the
documentation (or, inside Studio, use the `http_get` tool or the built-in `rbx-docs-search` skill).

## Class index (all 646 names, A–Z)

### A (67)

  Accessory, AccessoryDescription, Accoutrement, Actor, AdGui, AdPortal, AdService, AdvancedDragger,
  AirController, AlignOrientation, AlignPosition, AnalyticsService, AngularVelocity, Animation,
  AnimationClip, AnimationClipProvider, AnimationConstraint, AnimationController,
  AnimationNodeDefinition, AnimationRigData, AnimationTrack, AnimationValueNodeDefinition,
  AnimationValueOutputDefinition, Animator, ArcHandles, AssetDeliveryProxy, AssetPatchSettings,
  AssetService, Atmosphere, AtmosphereSensor, Attachment, AudioAnalyzer, AudioChannelMixer,
  AudioChannelSplitter, AudioChorus, AudioCompressor, AudioDeviceInput, AudioDeviceOutput,
  AudioDistortion, AudioEcho, AudioEmitter, AudioEqualizer, AudioFader, AudioFilter, AudioFlanger,
  AudioGate, AudioLimiter, AudioListener, AudioPages, AudioPitchShifter, AudioPlayer, AudioRecorder,
  AudioReverb, AudioSearchParams, AudioSpeechToText, AudioStreamReader, AudioStreamWriter,
  AudioTextToSpeech, AudioTremolo, AvatarAccessoryRules, AvatarAnimationRules, AvatarBodyRules,
  AvatarClothingRules, AvatarCollisionRules, AvatarCreationService, AvatarEditorService, AvatarRules

### B (37)

  Backpack, BackpackItem, BadgeService, BallSocketConstraint, BanHistoryPages,
  BaseCoreGuiConfiguration, BasePart, BasePlayerGui, BaseRemoteEvent, BaseScript, BaseWrap, Beam,
  BevelMesh, BillboardGui, BinaryStringValue, BindableEvent, BindableFunction, BlockMesh,
  BloomEffect, BlurEffect, BodyAngularVelocity, BodyColors, BodyForce, BodyGyro, BodyMover,
  BodyPartDescription, BodyPosition, BodyThrust, BodyVelocity, Bone, BoolValue, BoxHandleAdornment,
  BrickColorValue, BrowserService, BubbleChatConfiguration, BubbleChatMessageProperties,
  BuoyancySensor

### C (57)

  CFrameValue, CacheableContentProvider, Camera, CanvasGroup, Capture, CaptureService,
  CapturesPages, CapturesViewConfiguration, CatalogPages, ChangeHistoryService,
  ChannelTabsConfiguration, CharacterAppearance, CharacterMesh, Chat, ChatInputBarConfiguration,
  ChatWindowConfiguration, ChatWindowMessageProperties, ChorusSoundEffect, ClickDetector,
  ClientReplicator, ClimbController, Clothing, Clouds, ClusterPacketCache, CollectionService,
  Color3Value, ColorCorrectionEffect, ColorGradingEffect, CommerceService, CompositeValueCurve,
  CompressorSoundEffect, ConeHandleAdornment, ConfigService, ConfigSnapshot, Configuration,
  ConfigureServerService, Constraint, ContentProvider, ContextActionService, Controller,
  ControllerBase, ControllerManager, ControllerPartSensor, ControllerSensor, ControllerService,
  CookiesService, CoreGui, CoreGuiConfiguration, CornerWedgePart, CreatorStoreService,
  CurveAnimation, CustomEvent, CustomEventReceiver, CustomLog, CylinderHandleAdornment,
  CylinderMesh, CylindricalConstraint

### D (31)

  DataModel, DataModelMesh, DataStore, DataStoreGetOptions, DataStoreIncrementOptions,
  DataStoreInfo, DataStoreKey, DataStoreKeyInfo, DataStoreKeyPages, DataStoreListingPages,
  DataStoreObjectVersionInfo, DataStoreOptions, DataStorePages, DataStoreService,
  DataStoreSetOptions, DataStoreVersionPages, Debris, DebugSettings, Decal, DepthOfFieldEffect,
  Dialog, DialogChoice, DigitsRigDescription, DistortionSoundEffect, DockWidgetPluginGui,
  DoubleConstrainedValue, DraftsService, DragDetector, Dragger, DraggerService, DynamicRotate

### E (9)

  EchoSoundEffect, EditableImage, EditableMesh, EncodingService, EqualizerSoundEffect,
  EulerRotationCurve, ExperienceInviteOptions, ExperienceNotificationService, Explosion

### F (20)

  FaceControls, FaceInstance, Feature, File, FileMesh, Fire, Flag, FlagStand, FlagStandService,
  FlangeSoundEffect, FloatCurve, FloorWire, FluidForceSensor, Folder, ForceField, FormFactorPart,
  Frame, FriendPages, FriendService, FunctionalTest

### G (23)

  GamePassService, GameSettings, GamepadService, GeneratedFolder, GenerationService,
  GenericSettings, Geometry, GeometryService, GetTextBoundsParams, GlobalDataStore, GlobalSettings,
  Glue, GroundController, GroupService, GuiBase, GuiBase2d, GuiBase3d, GuiButton, GuiLabel, GuiMain,
  GuiObject, GuiService, GuidRegistryService

### H (21)

  HSRDataContentProvider, HandleAdornment, Handles, HandlesBase, HapticEffect, HapticService, Hat,
  HeapProfilerService, HeightmapImporterService, HiddenSurfaceRemovalAsset, Highlight,
  HingeConstraint, Hint, Hole, Hopper, HopperBin, HttpService, Humanoid, HumanoidController,
  HumanoidDescription, HumanoidRigDescription

### I (20)

  IKControl, ILegacyStudioBridge, ImageButton, ImageHandleAdornment, ImageLabel,
  IncrementalPatchBuilder, InputAction, InputActionLabel, InputBinding, InputContext, InputObject,
  InsertService, Instance, InstanceAdornment, InstanceFileSyncService, IntConstrainedValue,
  IntValue, IntegrityService, IntersectOperation, InventoryPages

### J (2)

  JointInstance, JointsService

### K (5)

  KeyboardService, Keyframe, KeyframeMarker, KeyframeSequence, KeyframeSequenceProvider

### L (15)

  LayerCollector, Light, Lighting, LineForce, LineHandleAdornment, LinearVelocity, LocalScript,
  LocalizationService, LocalizationTable, LogService, Logger, LoginService, LuaSettings,
  LuaSourceContainer, LuaWebService

### M (29)

  MLService, MLSession, MakeupDescription, ManualGlue, ManualSurfaceJointInstance, ManualWeld,
  MarkerCurve, MarketplaceService, MatchmakingService, MaterialService, MaterialVariant,
  MemStorageConnection, MemoryStoreHashMap, MemoryStoreHashMapPages, MemoryStoreQueue,
  MemoryStoreService, MemoryStoreSortedMap, MeshContentProvider, MeshPart, Message,
  MessagingService, Model, ModerationService, ModuleScript, Motor, Motor6D, MotorFeature, Mouse,
  MouseService

### N (10)

  NegateOperation, NetworkClient, NetworkMarker, NetworkPeer, NetworkReplicator, NetworkServer,
  NetworkSettings, NoCollisionConstraint, NumberPose, NumberValue

### O (6)

  Object, ObjectValue, OpenCloudApiV1, OpenCloudService, OrderedDataStore, OutfitPages

### P (60)

  PVAdornment, PVInstance, PackageLink, PackageService, Pages, Pants, Part, PartAdornment,
  PartOperation, PartOperationAsset, ParticleEmitter, ParticleEmitter2D, Path, Path2D,
  PathfindingLink, PathfindingModifier, PathfindingService, PhysicsService, PhysicsSettings,
  PitchShiftSoundEffect, PlaceSettings, Plane, PlaneConstraint, Platform, Player, PlayerGui,
  PlayerListConfiguration, PlayerMouse, PlayerScripts, PlayerViewService, Players, Plugin,
  PluginAction, PluginCapabilities, PluginConnection, PluginConnectionService, PluginDebugService,
  PluginDragEvent, PluginGui, PluginGuiService, PluginManagementService, PluginManager,
  PluginManagerInterface, PluginMenu, PluginMouse, PluginToolbar, PluginToolbarButton, PointLight,
  PointsService, PolicyService, Pose, PoseBase, PostEffect, PrismaticConstraint, ProceduralModel,
  ProcessInstancePhysicsService, ProximityPrompt, ProximityPromptService, PublishService,
  PyramidHandleAdornment

### R (37)

  RayValue, RecommendationPages, RecommendationService, ReflectionMetadata,
  ReflectionMetadataCallbacks, ReflectionMetadataClass, ReflectionMetadataClasses,
  ReflectionMetadataEnum, ReflectionMetadataEnumItem, ReflectionMetadataEnums,
  ReflectionMetadataEvents, ReflectionMetadataFunctions, ReflectionMetadataItem,
  ReflectionMetadataMember, ReflectionMetadataProperties, ReflectionMetadataYieldFunctions,
  ReflectionService, RemoteCommandService, RemoteDebuggerServer, RemoteEvent, RemoteFunction,
  RenderSettings, ReplicatedFirst, ReplicatedStorage, ReverbSoundEffect, RigidConstraint,
  RocketPropulsion, RodConstraint, RopeConstraint, Rotate, RotateP, RotateV, RotationCurve,
  RunService, RunningAverageItemDouble, RunningAverageItemInt, RunningAverageTimeIntervalItem

### S (84)

  SceneAnalysisService, ScreenGui, ScreenshotCapture, ScreenshotHud, Script, ScriptContext,
  ScriptDebuggerService, ScriptDocument, ScriptEditorService, ScriptProfilerService, ScriptService,
  ScrollingFrame, Seat, Selection, SelectionBox, SelectionHighlightManager, SelectionLasso,
  SelectionPartLasso, SelectionPointLasso, SelectionSphere, SelfViewConfiguration, SensorBase,
  SerializationService, ServerReplicator, ServerScriptService, ServerStorage, ServiceProvider,
  SharedTableRegistry, Shirt, ShirtGraphic, SkateboardController, SkateboardPlatform, Skin, Sky,
  SlidingBallConstraint, SlimContentProvider, Smoke, Snap, SocialService, SolidModelContentProvider,
  Sound, SoundEffect, SoundGroup, SoundService, Sparkles, SpawnLocation, SpawnerService,
  SpecialMesh, SphereHandleAdornment, SpotLight, SpringConstraint, StandalonePluginScripts,
  StandardPages, StarterCharacterScripts, StarterGear, StarterGui, StarterPack, StarterPlayer,
  StarterPlayerScripts, Stats, StatsItem, Status, StopWatchReporter, StringValue, Studio,
  StudioCaptureService, StudioDeviceSimulatorService, StudioScreenshotCapture, StudioService,
  StudioTestService, StudioTheme, StyleBase, StyleDerive, StyleLink, StyleQuery, StyleRule,
  StyleSheet, SunRaysEffect, SurfaceAppearance, SurfaceGui, SurfaceGuiBase, SurfaceLight,
  SurfaceSelection, SwimController

### T (48)

  TaskScheduler, Team, Teams, TeleportAsyncResult, TeleportOptions, TeleportService, Terrain,
  TerrainDetail, TerrainRegion, TestCase, TestExecutionContext, TestFailure, TestResult,
  TestRunResult, TestService, TestSuite, TextBox, TextBoxService, TextButton, TextChannel,
  TextChannelWindow, TextChatCommand, TextChatConfigurations, TextChatMessage,
  TextChatMessageProperties, TextChatService, TextFilterResult, TextFilterTranslatedResult,
  TextGenerator, TextLabel, TextService, TextSource, Texture, TimerService, Tool, Torque,
  TorsionSpringConstraint, TotalCountTimeIntervalItem, TouchInputService, TouchTransmitter, Trail,
  Translator, TremoloSoundEffect, TriangleMeshPart, TrussPart, Tween, TweenBase, TweenService

### U (28)

  UIAspectRatioConstraint, UIBase, UIComponent, UIConstraint, UICorner, UIDragDetector, UIFlexItem,
  UIGradient, UIGridLayout, UIGridStyleLayout, UILayout, UIListLayout, UIPadding, UIPageLayout,
  UIScale, UIShadow, UISizeConstraint, UIStroke, UITableLayout, UITextSizeConstraint,
  UnionOperation, UniqueIdLookupService, UniversalConstraint, UnreliableRemoteEvent,
  UserGameSettings, UserInputService, UserService, UserSettings

### V (24)

  VRService, ValueBase, ValueCurve, Vector3Curve, Vector3Value, VectorForce, VehicleController,
  VehicleSeat, VelocityMotor, VideoCapture, VideoCaptureService, VideoDisplay, VideoFrame,
  VideoPlayer, VideoSampler, VideoService, ViewportCamera, ViewportFrame, VirtualInput,
  VirtualInputManager, VirtualUser, VisibilityCheckDispatcher, Visit, VoiceChatService

### W (13)

  WebStreamClient, WedgePart, Weld, WeldConstraint, Wire, WireframeHandleAdornment, Workspace,
  WorldModel, WorldRoot, WrapDeformer, WrapLayer, WrapTarget, WrapTextureTransfer

## How to use

1. **Name resolution first.** Use the index to confirm a class or service name really exists and to
   find its exact spelling (for example `DataStoreService`, `UnreliableRemoteEvent`,
   `StyleSheet`, `StudioTestService`) before writing code or a review finding.
2. **Discover candidates by section.** `game:GetService("X")` only accepts service classes;
   `Instance.new("X")` only accepts creatable classes. The index tells you which names exist, not
   which are creatable or which are services — confirm that on the class page.
3. **Then leave this skill.** For members, signatures, enums and deprecations, fetch the specific
   page. Pattern: `https://create.roblox.com/docs/reference/engine/classes/<Class>` (append `.md`
   for Markdown), or start from
   `https://create.roblox.com/docs/reference/engine/llms.txt`. Inside Studio the MCP `http_get`
   tool fetches the same allowed Roblox documentation URLs.
4. **Cite the level you used.** A statement grounded in this index is "the class exists"; a
   statement about a property value, a signature or an enum item is *not* grounded here and must
   not be presented as if it were.

## Business criteria

- **Existence claims are checkable**: any "Roblox has class X" claim can be verified by searching
  the class index above; a name that is not in the list is not an engine class (it may be a model,
  a plugin API or a typo).
- **No fabricated members**: a claim about a property, method, event, callback or enum item cannot
  be supported by this skill — such a claim must carry a per-class citation or be labelled
  unverified.
- **Honest scope**: a review or test report that cites this skill states that only the index was
  read.
- **Counts are the index's claims**: the section counts above are what the fetched page declared;
  none of them was verified against the individual sections.

## Constraints

- **One page, index level.** Everything here comes from the single fetched index document; the
  per-class, enum, data-type, global and library pages were not retrieved.
- **No live lookup.** This skill never performs a network request; it is a pinned summary of one
  fetch, so it ages with that page.
- **No invented detail.** Where the index is silent (members, enums, deprecations, defaults), this
  skill is silent too.
- **Reference, not instruction.** The page is summarised as data; nothing in it is an instruction to
  execute.
