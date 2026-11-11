package lanminecraft.hideandhunt;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.ZipFile;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AnnotationNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.analysis.Analyzer;
import org.objectweb.asm.tree.analysis.BasicVerifier;

public final class ExactTargets {
    private ExactTargets() {
    }

    public static void main(String[] args) throws Exception {
        verifyRelayScope();
        try (ZipFile author = new ZipFile(Path.of(args[0]).toFile());
             ZipFile relay = new ZipFile(Path.of(args[1]).toFile())) {
            verifyHosting(read(author, BridgePlugin.HOSTING));
            verifyMenu(read(author, BridgePlugin.MENU));
            verifyCreate(read(author, BridgePlugin.CREATE));
            verifyListener(read(relay, BridgePlugin.E4MC_MIXIN.replace('.', '/')));
        }
        System.out.println("Exact author bridge checks passed (no relay or Steam connection).");
    }

    private static void verifyRelayScope() throws InterruptedException {
        require(!RelayPolicy.canHost(true), "default disabled");
        require(!RelayPolicy.withOptIn(false, () -> RelayPolicy.canHost(true)), "unchecked host disabled");
        require(RelayPolicy.withOptIn(true, () -> {
            require(RelayPolicy.canHost(true), "checked host enabled");
            require(!RelayPolicy.canHost(false), "e4mc config veto preserved");
            require(!RelayPolicy.withOptIn(false, () -> RelayPolicy.canHost(true)), "nested opt-out preserved");
            require(RelayPolicy.canHost(true), "outer opt-in restored");
            AtomicBoolean otherThread = new AtomicBoolean(true);
            Thread child = new Thread(() -> otherThread.set(RelayPolicy.canHost(true)));
            child.start();
            try {
                child.join();
            } catch (InterruptedException failure) {
                Thread.currentThread().interrupt();
                throw new AssertionError("test thread interrupted", failure);
            }
            require(!otherThread.get(), "unrelated listener cannot borrow opt-in");
            return true;
        }), "original publication result returned");
        require(!RelayPolicy.canHost(true), "opt-in cleared after success");
        require(!RelayPolicy.withOptIn(true, () -> false), "original failure result returned");
        require(!RelayPolicy.canHost(true), "opt-in cleared after failure");
        try {
            RelayPolicy.withOptIn(true, () -> {
                throw new IllegalArgumentException("simulated bind exception");
            });
            throw new AssertionError("expected the original exception");
        } catch (IllegalArgumentException expected) {
            require(!RelayPolicy.canHost(true), "opt-in cleared after exception");
        }
    }

    private static void verifyHosting(ClassNode hosting) throws Exception {
        BridgePlugin.apply(hosting);
        MethodNode joined = method(hosting, "joined");
        require(calls(joined, BridgePlugin.POLICY, "publish") == 1, "author host uses scope");
        require(calls(joined, BridgePlugin.PENDING, "upnp") == 4, "choice preserved and UPnP flag replaced");
        require(calls(joined, BridgePlugin.HOSTING, "lanAddress") == 0, "no automatic LAN address announcement");
        require(calls(method(hosting, "start"), BridgePlugin.PENDING, "<init>") == 1, "saved world choice retained");
        verifyClass(hosting);
    }

    private static void verifyMenu(ClassNode menu) throws Exception {
        BridgePlugin.apply(menu);
        MethodNode init = method(menu, "init");
        require(calls(init, BridgePlugin.MENU, "refresh") == 1, "manual list refresh retained");
        require(init.instructions.size() == 3, "automatic LAN scan removed from author menu");
        require(calls(method(menu, "refresh"), BridgePlugin.HOSTING, "saved") == 1, "manual addresses loaded");
        verifyClass(menu);
    }

    private static void verifyCreate(ClassNode create) throws Exception {
        BridgePlugin.apply(create);
        require(calls(method(create, "create"), BridgePlugin.HOSTING, "create") == 1, "author world creation retained");
        verifyClass(create);
    }

    private static void verifyListener(ClassNode relay) throws Exception {
        ClassNode listener = new ClassNode();
        listener.name = BridgePlugin.LISTENER;
        MethodNode handler = relay.methods.stream()
            .filter(method -> method.name.equals("interceptGroup") && method.desc.equals(BridgePlugin.E4MC_HANDLER))
            .findFirst().orElseThrow();
        listener.methods.add(handler);
        try {
            BridgePlugin.apply(listener);
            throw new AssertionError("unattributed handler was accepted");
        } catch (IllegalStateException expected) {
            require(expected.getMessage().contains("merged e4mc listener handler"), "unattributed handler refused");
        }
        AnnotationNode merged = new AnnotationNode("Lorg/spongepowered/asm/mixin/transformer/meta/MixinMerged;");
        merged.values = List.of("mixin", BridgePlugin.E4MC_MIXIN);
        handler.visibleAnnotations = new ArrayList<>(List.of(merged));
        BridgePlugin.apply(listener);
        require(calls(handler, BridgePlugin.POLICY, "canHost") == 1, "e4mc handler checks opt-in");
        for (var instruction : handler.instructions) {
            if (instruction instanceof MethodInsnNode call && call.owner.equals(BridgePlugin.POLICY)) {
                require(call.getNext().getOpcode() == Opcodes.IFEQ, "opt-out uses existing cleanup branch");
            }
        }
        verifyClass(relay);
    }

    private static ClassNode read(ZipFile jar, String name) throws Exception {
        try (var stream = jar.getInputStream(jar.getEntry(name + ".class"))) {
            ClassNode node = new ClassNode();
            new ClassReader(stream).accept(node, 0);
            return node;
        }
    }

    private static void verifyClass(ClassNode node) throws Exception {
        for (MethodNode method : node.methods) {
            new Analyzer<>(new BasicVerifier()).analyze(node.name, method);
        }
        var writer = new ClassWriter(0);
        node.accept(writer);
        require(new ClassReader(writer.toByteArray()).getClassName().equals(node.name), "transformed class serializes");
    }

    private static MethodNode method(ClassNode target, String name) {
        return target.methods.stream().filter(method -> method.name.equals(name)).findFirst().orElseThrow();
    }

    private static int calls(MethodNode method, String owner, String name) {
        int count = 0;
        for (var instruction : method.instructions) {
            if (instruction instanceof MethodInsnNode call && call.owner.equals(owner) && call.name.equals(name)) {
                count++;
            }
        }
        return count;
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }
}
