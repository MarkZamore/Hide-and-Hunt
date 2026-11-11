package lanminecraft.hideandhunt;

import java.io.IOException;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import net.fabricmc.loader.api.FabricLoader;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.AnnotationNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.FieldInsnNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TypeInsnNode;
import org.objectweb.asm.tree.VarInsnNode;
import org.spongepowered.asm.mixin.extensibility.IMixinConfigPlugin;
import org.spongepowered.asm.mixin.extensibility.IMixinInfo;

public final class BridgePlugin implements IMixinConfigPlugin {
    static final String HOSTING = "de/hideandhunt/client/host/Hosting";
    static final String PENDING = HOSTING + "$Pending";
    static final String CREATE = "de/hideandhunt/client/screen/CreateWorldView";
    static final String MENU = "de/hideandhunt/client/screen/HhMenuView";
    static final String LISTENER = "net/minecraft/server/network/ServerConnectionListener";
    static final String E4MC_MIXIN = "link.e4mc.mixin.ServerConnectionListenerMixin";
    static final String E4MC_HANDLER = "(Ljava/net/InetAddress;ILorg/spongepowered/asm/mixin/injection/callback/CallbackInfo;)V";
    static final String PUBLISH = "(Lnet/minecraft/server/MinecraftServer$MultiplayerScope;ZI)Z";
    static final String SERVER = "net/minecraft/client/server/IntegratedServer";
    static final String POLICY = "lanminecraft/hideandhunt/RelayPolicy";
    private static final String TRACKED_VALUE = "folk/sisby/kaleido/lib/quiltconfig/api/values/TrackedValue";
    private static final String DRAW = "(Lde/hideandhunt/client/ui/Canvas;IIF)V";
    private static final String TEXT = "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;[Ljava/lang/Object;)Lnet/minecraft/network/chat/MutableComponent;";

    @Override
    public void onLoad(String mixinPackage) {
        verifyOrigin("hideandhunt", HOSTING, "e04e557bbaf303b416e6e174b32d128dc53cdd29d3786add530f39bf27af1963");
        verifyOrigin("hideandhunt", PENDING, "473ea2e9bb882aaf2a37e1f04f9439533d5a592ded6c6acbdf7cc8a2f1b403af");
        verifyOrigin("hideandhunt", CREATE, "4652c5ff1a0a53280cee61bcc2aaa2e766f010bec769d07f4eedc65055b82fa3");
        verifyOrigin("hideandhunt", MENU, "e1b138a43962f4c54ea44af99b8525f0e9916569e20aca3e205bfa228a4e8dec");
        verifyOrigin("e4mc", E4MC_MIXIN.replace('.', '/'), "f68da7dfdfcecf04bc0509caf2feec41d080245db1035fdd581d6b79c2008fb9");
    }

    private static void verifyOrigin(String mod, String className, String expected) {
        var container = FabricLoader.getInstance().getModContainer(mod)
            .orElseThrow(() -> incompatible("missing " + mod));
        var path = container.findPath(className + ".class")
            .orElseThrow(() -> incompatible("missing " + className));
        try {
            byte[] hash = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path));
            if (!HexFormat.of().formatHex(hash).equals(expected)) {
                throw incompatible("unexpected bytes for " + className);
            }
        } catch (IOException | NoSuchAlgorithmException failure) {
            throw new IllegalStateException("Cannot check Hide and Hunt bridge class " + className, failure);
        }
    }

    @Override
    public void postApply(String targetClassName, ClassNode target, String mixinClassName, IMixinInfo mixinInfo) {
        // Mixin has merged the native e4mc handler before any postApply call.
        apply(target);
    }

    static void apply(ClassNode target) {
        switch (target.name) {
            case HOSTING -> patchHosting(target);
            case CREATE -> patchCreate(target);
            case MENU -> patchMenu(target);
            case LISTENER -> patchListener(target);
            default -> throw incompatible("unexpected target " + target.name);
        }
    }

    private static void patchHosting(ClassNode target) {
        MethodNode joined = method(target, "joined", "()V");
        MethodInsnNode publication = call(joined, Opcodes.INVOKEVIRTUAL, SERVER, "publishServer", PUBLISH);
        AbstractInsnNode portAdd = previous(publication);
        AbstractInsnNode attempt = previous(portAdd);
        AbstractInsnNode getPort = previous(attempt);
        AbstractInsnNode pending = previous(getPort);
        if (portAdd.getOpcode() != Opcodes.IADD || attempt.getOpcode() != Opcodes.ILOAD
            || !isCall(getPort, Opcodes.INVOKEVIRTUAL, PENDING, "port", "()I")
            || !(pending instanceof VarInsnNode local) || pending.getOpcode() != Opcodes.ALOAD) {
            throw incompatible("unknown author publication arguments");
        }

        List<MethodInsnNode> internetChecks = calls(joined, Opcodes.INVOKEVIRTUAL, PENDING, "upnp", "()Z");
        if (internetChecks.size() != 4) {
            throw incompatible("unknown author internet choices");
        }
        MethodInsnNode upnpFallback = internetChecks.getLast();
        if (next(upnpFallback).getOpcode() != Opcodes.IFEQ) {
            throw incompatible("unknown author UPnP fallback");
        }
        call(method(target, "lambda$joined$1", "(ILnet/minecraft/client/Minecraft;)V"),
            Opcodes.INVOKESTATIC, "de/hideandhunt/client/host/Upnp", "open",
            "(I)Lde/hideandhunt/client/host/Upnp$Mapping;");

        // The pending record is consumed in joined() before publication.
        // Read its world-specific choice from the live local for each port attempt.
        joined.instructions.insertBefore(publication, new VarInsnNode(Opcodes.ALOAD, local.var));
        joined.instructions.insertBefore(publication,
            new MethodInsnNode(Opcodes.INVOKEVIRTUAL, PENDING, "upnp", "()Z", false));
        joined.instructions.set(publication, new MethodInsnNode(Opcodes.INVOKESTATIC, POLICY, "publish",
            "(L" + SERVER + ";Lnet/minecraft/server/MinecraftServer$MultiplayerScope;ZIZ)Z", false));
        joined.maxStack += 1;

        joined.instructions.insertBefore(upnpFallback, new InsnNode(Opcodes.POP));
        joined.instructions.set(upnpFallback, new InsnNode(Opcodes.ICONST_0));
        MethodInsnNode lanAddress = call(joined, Opcodes.INVOKESTATIC, HOSTING, "lanAddress", "()Ljava/lang/String;");
        joined.instructions.set(lanAddress, new InsnNode(Opcodes.ACONST_NULL));
        replaceText(joined, "hh.host.open", "world.open",
            "Deine Welt ist offen. Steam-Freunde finden sie im Mehrspielermenü.",
            "Your world is open. Steam friends can find it in Multiplayer.");
    }

    private static void patchCreate(ClassNode target) {
        MethodNode draw = method(target, "draw", DRAW);
        replaceText(draw, "hh.cw.upnp", "e4mc", "Über e4mc", "Via e4mc");
        replaceText(draw, "hh.cw.upnp.e4mc", "e4mc.hint",
            "Erstellt eine e4mc-Adresse zum manuellen Teilen.",
            "Creates an e4mc address you can share manually.");
        replaceText(draw, "hh.cw.upnp.hint2", "e4mc.unavailable",
            "e4mc ist nicht verfügbar.", "e4mc is unavailable.");
    }

    private static void patchMenu(ClassNode target) {
        MethodNode init = method(target, "init", "()V");
        MethodInsnNode refresh = call(init, Opcodes.INVOKEVIRTUAL, MENU, "refresh", "()V");
        call(init, Opcodes.INVOKEVIRTUAL,
            "net/minecraft/client/server/LanServerDetection$LanServerDetector", "start", "()V");
        if (!(previous(refresh) instanceof VarInsnNode receiver)
            || receiver.getOpcode() != Opcodes.ALOAD || receiver.var != 0) {
            throw incompatible("unknown menu refresh");
        }
        // Keep local worlds and manual addresses. The automatic list belongs to
        // Minecraft's Multiplayer screen and the shared Steam discovery adapter.
        init.instructions.clear();
        init.tryCatchBlocks.clear();
        init.localVariables = null;
        init.instructions.add(new VarInsnNode(Opcodes.ALOAD, 0));
        init.instructions.add(new MethodInsnNode(refresh.getOpcode(), refresh.owner, refresh.name, refresh.desc, false));
        init.instructions.add(new InsnNode(Opcodes.RETURN));
        init.maxStack = 1;
        init.maxLocals = 1;

        MethodNode draw = method(target, "draw", DRAW);
        replaceText(draw, "hh.mm.join.none", "saved.empty", "Keine gespeicherten Adressen.", "No saved addresses.");
        replaceText(draw, "hh.mm.join.none2", "saved.hint",
            "Steam-Welten stehen im Mehrspielermenü.", "Find Steam worlds in Multiplayer.");
    }

    private static void patchListener(ClassNode target) {
        List<MethodNode> handlers = target.methods.stream()
            .filter(method -> method.desc.equals(E4MC_HANDLER) && fromE4mc(method.visibleAnnotations))
            .toList();
        if (handlers.size() != 1) {
            throw incompatible("expected one merged e4mc listener handler");
        }
        MethodNode handler = handlers.getFirst();
        call(handler, Opcodes.INVOKEVIRTUAL, "link/e4mc/QuiclimeSession", "startAsync", "()V");
        List<FieldInsnNode> reads = new ArrayList<>();
        for (AbstractInsnNode instruction : handler.instructions) {
            if (instruction instanceof FieldInsnNode field && field.getOpcode() == Opcodes.GETFIELD
                && field.owner.equals("link/e4mc/Config") && field.name.equals("hostEnabled")
                && field.desc.equals("L" + TRACKED_VALUE + ";")) {
                reads.add(field);
            }
        }
        if (reads.size() != 1) {
            throw incompatible("expected one e4mc hostEnabled read");
        }
        AbstractInsnNode value = next(reads.getFirst());
        AbstractInsnNode cast = next(value);
        AbstractInsnNode unbox = next(cast);
        if (!isCall(value, Opcodes.INVOKEINTERFACE, TRACKED_VALUE, "value", "()Ljava/lang/Object;")
            || !(cast instanceof TypeInsnNode type) || cast.getOpcode() != Opcodes.CHECKCAST
            || !type.desc.equals("java/lang/Boolean")
            || !isCall(unbox, Opcodes.INVOKEVIRTUAL, "java/lang/Boolean", "booleanValue", "()Z")
            || next(unbox).getOpcode() != Opcodes.IFEQ) {
            throw incompatible("unknown e4mc relay gate");
        }
        // Reuse e4mc's own disabled path, which clears captured Netty state.
        handler.instructions.insert(unbox,
            new MethodInsnNode(Opcodes.INVOKESTATIC, POLICY, "canHost", "(Z)Z", false));
    }

    private static boolean fromE4mc(List<AnnotationNode> annotations) {
        if (annotations == null) {
            return false;
        }
        for (AnnotationNode annotation : annotations) {
            if (annotation.desc.equals("Lorg/spongepowered/asm/mixin/transformer/meta/MixinMerged;")) {
                for (int index = 0; index < annotation.values.size(); index += 2) {
                    if (annotation.values.get(index).equals("mixin")
                        && annotation.values.get(index + 1).equals(E4MC_MIXIN)) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    private static void replaceText(MethodNode method, String key, String suffix, String german, String english) {
        List<LdcInsnNode> keys = new ArrayList<>();
        for (AbstractInsnNode instruction : method.instructions) {
            if (instruction instanceof LdcInsnNode constant && key.equals(constant.cst)) {
                keys.add(constant);
            }
        }
        if (keys.size() != 1) {
            throw incompatible("expected one text key " + key);
        }
        LdcInsnNode sourceKey = keys.getFirst();
        AbstractInsnNode germanSource = next(sourceKey);
        AbstractInsnNode englishSource = next(germanSource);
        AbstractInsnNode count = next(englishSource);
        AbstractInsnNode array = next(count);
        if (!(germanSource instanceof LdcInsnNode de) || !(de.cst instanceof String)
            || !(englishSource instanceof LdcInsnNode en) || !(en.cst instanceof String)
            || count.getOpcode() != Opcodes.ICONST_0 || array.getOpcode() != Opcodes.ANEWARRAY
            || !isCall(next(array), Opcodes.INVOKESTATIC, "de/hideandhunt/T", "c", TEXT)) {
            throw incompatible("unknown text call for " + key);
        }
        sourceKey.cst = "lanminecraft.hideandhunt." + suffix;
        de.cst = german;
        en.cst = english;
    }

    private static MethodNode method(ClassNode target, String name, String descriptor) {
        return target.methods.stream()
            .filter(method -> method.name.equals(name) && method.desc.equals(descriptor))
            .findFirst().orElseThrow(() -> incompatible(target.name + "." + name + descriptor));
    }

    private static MethodInsnNode call(MethodNode method, int opcode, String owner, String name, String descriptor) {
        List<MethodInsnNode> matches = calls(method, opcode, owner, name, descriptor);
        if (matches.size() != 1) {
            throw incompatible("expected one call to " + owner + "." + name + " in " + method.name);
        }
        return matches.getFirst();
    }

    private static List<MethodInsnNode> calls(MethodNode method, int opcode, String owner, String name, String descriptor) {
        List<MethodInsnNode> matches = new ArrayList<>();
        for (AbstractInsnNode instruction : method.instructions) {
            if (isCall(instruction, opcode, owner, name, descriptor)) {
                matches.add((MethodInsnNode) instruction);
            }
        }
        return matches;
    }

    private static boolean isCall(AbstractInsnNode instruction, int opcode, String owner, String name, String descriptor) {
        return instruction instanceof MethodInsnNode call && call.getOpcode() == opcode
            && call.owner.equals(owner) && call.name.equals(name) && call.desc.equals(descriptor);
    }

    private static AbstractInsnNode previous(AbstractInsnNode instruction) {
        do {
            instruction = instruction.getPrevious();
        } while (instruction != null && instruction.getOpcode() < 0);
        if (instruction == null) {
            throw incompatible("missing previous bytecode instruction");
        }
        return instruction;
    }

    private static AbstractInsnNode next(AbstractInsnNode instruction) {
        do {
            instruction = instruction.getNext();
        } while (instruction != null && instruction.getOpcode() < 0);
        if (instruction == null) {
            throw incompatible("missing next bytecode instruction");
        }
        return instruction;
    }

    private static IllegalStateException incompatible(String reason) {
        return new IllegalStateException("Hide and Hunt bridge requires its pinned upstream profile: " + reason);
    }

    @Override
    public String getRefMapperConfig() {
        return null;
    }

    @Override
    public boolean shouldApplyMixin(String targetClassName, String mixinClassName) {
        return true;
    }

    @Override
    public void acceptTargets(Set<String> myTargets, Set<String> otherTargets) {
    }

    @Override
    public List<String> getMixins() {
        return null;
    }

    @Override
    public void preApply(String targetClassName, ClassNode targetClass, String mixinClassName, IMixinInfo mixinInfo) {
    }
}
